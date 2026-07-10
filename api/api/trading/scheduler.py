"""Event-driven trading scheduler: agents wake by their own will.

Every 5 minutes during market hours a cheap "tick" runs per market:
1. expire stale intents
2. fetch prices for tickers referenced by intents + held positions
3. execute triggered conditional orders WITHOUT waking anyone (the agent
   pre-committed; the system just honors it)
4. wake agents whose scheduled time arrived, whose wake triggers hit,
   or whose conditional orders just filled
5. each woken agent researches (live web search), decides, places new
   intents, writes its journal, and chooses when to wake next

There is no risk cage: the only rules enforced at execution are physics
(cash cannot go negative, no shorting, no selling shares you don't own —
all inside SimulatedPortfolio) plus real transaction costs. Agents own
their own risk. This is a deliberate design decision for the paper-money
arena; rails must return before any real-money use.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from api.data.batch import fetch_batch_history
from api.data.market import get_portfolio_prices
from api.data.news import get_news_summary
from api.db.sqlite import db
from api.llm.client import LLMClient
from api.quant.signals import compute_batch_signals, format_batch_signal_cards
from api.quant.factors import compute_factor_scores, format_factor_report
from api.quant.regime import detect_regime
from api.quant.insider import get_insider_signals
from api.quant.ml_combiner import combine_signals, format_combined_report
from api.quant.earnings import analyze_earnings_news, format_earnings_report
from api.quant.anomaly import detect_anomalies, format_anomaly_report
from api.trading.market_hours import is_market_open
from api.trading.models import TradeDecision, TradeOrder
from api.trading.portfolio import STARTING_CAPITAL, SimulatedPortfolio
from api.trading.strategies import ALL_STRATEGIES, TradingStrategy
from api.trading.strategies_tw import ALL_TW_STRATEGIES

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
TW_TZ = ZoneInfo("Asia/Taipei")

TW_STARTING_CAPITAL = 300_000.0

# Agents choose their own cadence within these bounds
MIN_SLEEP_HOURS = 0.25
MAX_SLEEP_HOURS = 48.0
WAKE_TRIGGER_TTL_DAYS = 14


def _trigger_hit(trigger_type: str, trigger_price: float, price: float) -> bool:
    if trigger_type == "price_below":
        return price < trigger_price
    if trigger_type == "price_at_or_above":
        return price >= trigger_price
    return False


class TradingScheduler:
    """Runs the tick loop and manages agent lifecycles for both markets."""

    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone=ET)
        self._llm = LLMClient()
        self._portfolios: dict[str, SimulatedPortfolio] = {}
        self._tw_portfolios: dict[str, SimulatedPortfolio] = {}
        self._cycle_count = 0
        self._tw_cycle_count = 0
        self._running = False
        self._lock = threading.Lock()
        self._tw_lock = threading.Lock()
        self._last_cycle_results: list[dict[str, Any]] = []
        self._last_tw_cycle_results: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Introspection (used by routes)
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    @property
    def tw_cycle_count(self) -> int:
        return self._tw_cycle_count

    @property
    def last_cycle_results(self) -> list[dict[str, Any]]:
        return self._last_cycle_results

    @property
    def last_tw_cycle_results(self) -> list[dict[str, Any]]:
        return self._last_tw_cycle_results

    def get_portfolios(self) -> dict[str, SimulatedPortfolio]:
        return dict(self._portfolios)

    def get_tw_portfolios(self) -> dict[str, SimulatedPortfolio]:
        return dict(self._tw_portfolios)

    def get_portfolio(self, strategy: str) -> SimulatedPortfolio | None:
        return self._portfolios.get(strategy)

    def get_tw_portfolio(self, strategy: str) -> SimulatedPortfolio | None:
        return self._tw_portfolios.get(strategy)

    def get_agent_states(self) -> list[dict[str, Any]]:
        """Wake schedule + watchlist per agent (for the status endpoint)."""
        states = []
        for s in ALL_STRATEGIES + ALL_TW_STRATEGIES:
            st = db.get_agent_state(s.name)
            if st:
                states.append(st)
        return states

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Load portfolio states from DB and initialize missing ones."""
        db.init_db()
        for strategy in ALL_STRATEGIES:
            saved = db.load_portfolio_state(strategy.name)
            if saved:
                self._portfolios[strategy.name] = SimulatedPortfolio.from_dict(saved)
                logger.info("Loaded portfolio for %s from DB", strategy.name)
            else:
                self._portfolios[strategy.name] = SimulatedPortfolio(
                    strategy=strategy.name, cash=STARTING_CAPITAL
                )
                logger.info("Created new portfolio for %s", strategy.name)

        for strategy in ALL_TW_STRATEGIES:
            saved = db.load_portfolio_state(strategy.name)
            if saved:
                self._tw_portfolios[strategy.name] = SimulatedPortfolio.from_dict(saved)
                logger.info("Loaded TW portfolio for %s from DB", strategy.name)
            else:
                self._tw_portfolios[strategy.name] = SimulatedPortfolio(
                    strategy=strategy.name,
                    cash=TW_STARTING_CAPITAL,
                    currency="TWD",
                    starting_capital=TW_STARTING_CAPITAL,
                )
                logger.info("Created new TW portfolio for %s", strategy.name)

        # Agent states: first boot of a season wakes everyone on the next tick
        now_iso = datetime.now(timezone.utc).isoformat()
        for strategy in ALL_STRATEGIES + ALL_TW_STRATEGIES:
            if db.get_agent_state(strategy.name) is None:
                db.save_agent_state(
                    strategy.name,
                    next_wakeup=now_iso,
                    watchlist=list(strategy.watchlist or []),
                )

    def start(self) -> None:
        """Start the tick loop for both markets."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self.initialize()

        self._scheduler.add_job(
            lambda: self._tick("us"),
            CronTrigger(day_of_week="mon-fri", hour="9-16", minute="*/5", timezone=ET),
            id="us_tick", replace_existing=True, max_instances=1, coalesce=True,
        )
        self._scheduler.add_job(
            lambda: self._tick("tw"),
            CronTrigger(day_of_week="mon-fri", hour="9-13", minute="*/5", timezone=TW_TZ),
            id="tw_tick", replace_existing=True, max_instances=1, coalesce=True,
        )

        self._scheduler.start()
        self._running = True
        logger.info("Trading scheduler started (event-driven ticks, US + TW)")

    def stop(self) -> None:
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Trading scheduler stopped")

    def get_next_run_time(self) -> str | None:
        job = self._scheduler.get_job("us_tick")
        return job.next_run_time.isoformat() if job and job.next_run_time else None

    def get_tw_next_run_time(self) -> str | None:
        job = self._scheduler.get_job("tw_tick")
        return job.next_run_time.isoformat() if job and job.next_run_time else None

    # ------------------------------------------------------------------
    # The tick
    # ------------------------------------------------------------------

    def _tick(self, market: str, force_wake_all: bool = False) -> list[dict[str, Any]]:
        if not force_wake_all and not is_market_open(market):
            return []

        lock = self._tw_lock if market == "tw" else self._lock
        strategies = ALL_TW_STRATEGIES if market == "tw" else ALL_STRATEGIES
        portfolios = self._tw_portfolios if market == "tw" else self._portfolios

        with lock:
            if not portfolios:
                self.initialize()

            now = datetime.now(timezone.utc)
            db.expire_stale_intents()

            strategy_names = {s.name for s in strategies}
            intents = [i for i in db.get_active_intents() if i["strategy"] in strategy_names]

            # Prices for everything the sleeping agents care about
            price_tickers = {i["ticker"] for i in intents}
            for p in portfolios.values():
                price_tickers.update(p.positions.keys())
            prices = get_portfolio_prices(list(price_tickers)) if price_tickers else {}
            for p in portfolios.values():
                p.update_prices(prices)

            # 1. Honor pre-committed conditional orders (no LLM involved)
            fills_by_strategy: dict[str, list[dict[str, Any]]] = {}
            for intent in intents:
                if intent["kind"] != "conditional_order":
                    continue
                price = prices.get(intent["ticker"], 0.0)
                if price <= 0 or not _trigger_hit(intent["trigger_type"], intent["trigger_price"], price):
                    continue
                portfolio = portfolios[intent["strategy"]]
                order = TradeOrder(
                    action=intent["action"], ticker=intent["ticker"],
                    shares=intent["shares"],
                    reason=f"[conditional] {intent['reason']}",
                )
                record = portfolio.execute_order(order, price)
                if record:
                    record.id = db.save_trade(record)
                    db.set_intent_status(intent["id"], "filled", record.id)
                    db.save_portfolio_state(intent["strategy"], json.dumps(portfolio.to_dict()))
                    fills_by_strategy.setdefault(intent["strategy"], []).append({
                        "action": record.action, "ticker": record.ticker,
                        "shares": record.shares, "price": record.price,
                        "reason": intent["reason"],
                    })
                    logger.info("[%s] CONDITIONAL FILL: %s %s x%d @ %.2f",
                                intent["strategy"], record.action, record.ticker,
                                record.shares, price)
                else:
                    # Physics rejected it (e.g. cash spent elsewhere) — cancel
                    db.set_intent_status(intent["id"], "cancelled")

            # 2. Periodic snapshots (every ~30 min, prices permitting)
            if now.minute % 30 < 5 or force_wake_all:
                for name, portfolio in portfolios.items():
                    if all(p.current_price > 0 for p in portfolio.positions.values()):
                        db.save_snapshot(name, now, portfolio.total_value)

            # 3. Who wakes up?
            wake_reasons: dict[str, str] = {}
            for s in strategies:
                state = db.get_agent_state(s.name)
                if force_wake_all:
                    wake_reasons[s.name] = "manual trigger (forced wake)"
                    continue
                if s.name in fills_by_strategy:
                    f = fills_by_strategy[s.name][0]
                    wake_reasons[s.name] = (
                        f"your conditional order filled: {f['action']} {f['ticker']} x{f['shares']} @ {f['price']:.2f}"
                    )
                    continue
                if state and state["next_wakeup"] <= now.isoformat():
                    wake_reasons[s.name] = "scheduled check-in (your chosen time)"
                    continue
                for intent in intents:
                    if intent["strategy"] == s.name and intent["kind"] == "wake_trigger":
                        price = prices.get(intent["ticker"], 0.0)
                        if price > 0 and _trigger_hit(intent["trigger_type"], intent["trigger_price"], price):
                            db.set_intent_status(intent["id"], "triggered")
                            wake_reasons[s.name] = (
                                f"your wake trigger hit: {intent['ticker']} {intent['trigger_type']} "
                                f"{intent['trigger_price']:.2f} (now {price:.2f})"
                            )
                            break

            if not wake_reasons:
                return []

            results = self._wake_agents(market, strategies, portfolios, wake_reasons, fills_by_strategy)

            if market == "tw":
                self._tw_cycle_count += 1
                self._last_tw_cycle_results = results
            else:
                self._cycle_count += 1
                self._last_cycle_results = results
            return results

    # ------------------------------------------------------------------
    # Waking agents
    # ------------------------------------------------------------------

    def _wake_agents(
        self,
        market: str,
        strategies: list[TradingStrategy],
        portfolios: dict[str, SimulatedPortfolio],
        wake_reasons: dict[str, str],
        fills_by_strategy: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        tz = TW_TZ if market == "tw" else ET
        today_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M (%A)") + (
            " Asia/Taipei" if market == "tw" else " US/Eastern"
        )
        awake = [s for s in strategies if s.name in wake_reasons]
        logger.info("[%s] Waking %d agents: %s", market.upper(), len(awake), list(wake_reasons))

        # Shared research universe: watchlists + holdings of woken agents
        agent_states = {s.name: db.get_agent_state(s.name) or {"watchlist": [], "next_wakeup": ""} for s in awake}
        all_tickers: set[str] = set()
        for s in awake:
            all_tickers.update(agent_states[s.name]["watchlist"][:20])
            all_tickers.update(portfolios[s.name].positions.keys())
        if not all_tickers:
            all_tickers = (
                {"2330.TW", "2317.TW", "2454.TW"} if market == "tw"
                else {"NVDA", "AAPL", "MSFT"}
            )
        ticker_list = list(all_tickers)

        full_report, signals, cycle_prices, pipeline_data = self._build_research(market, ticker_list)
        news = get_news_summary(ticker_list[:6])

        for p in portfolios.values():
            p.update_prices(cycle_prices)

        # Per-agent context: journal, intents, fills, scoreboard
        contexts: dict[str, dict[str, Any]] = {}
        for s in awake:
            portfolio = portfolios[s.name]
            day_start = (
                datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
                .astimezone(timezone.utc).isoformat()
            )
            baseline = db.get_first_snapshot_since(s.name, day_start)
            today_pnl = ((portfolio.total_value / baseline - 1) * 100) if baseline else 0.0
            peak = db.get_peak_value(s.name) or portfolio.total_value
            drawdown = ((portfolio.total_value / peak - 1) * 100) if peak > 0 else 0.0
            contexts[s.name] = {
                "today": today_str,
                "wake_reason": wake_reasons[s.name],
                "journal": db.get_recent_journal(s.name, limit=5),
                "intents": db.get_active_intents(s.name),
                "fills": fills_by_strategy.get(s.name, []),
                "status": {"today_pnl_pct": today_pnl, "drawdown_pct": drawdown},
                "watchlist": agent_states[s.name]["watchlist"],
            }

        # LLM decisions in parallel (research + decide per agent)
        decisions: dict[str, TradeDecision] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(awake))) as executor:
            futures = {
                executor.submit(
                    s.decide, self._llm, portfolios[s.name].get_state(),
                    full_report, news, contexts[s.name],
                ): s.name
                for s in awake
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    decisions[name] = future.result()
                except Exception as e:
                    logger.error("Agent %s failed to decide: %s", name, e, exc_info=True)

        # Execute decisions — physics only
        results: list[dict[str, Any]] = []
        for s in awake:
            name = s.name
            if name not in decisions:
                # LLM failed: sleep an hour and retry later
                db.save_agent_state(
                    name,
                    next_wakeup=(now + timedelta(hours=1)).isoformat(),
                    watchlist=contexts[name]["watchlist"],
                )
                continue

            decision = decisions[name]
            portfolio = portfolios[name]
            trades_executed: list[dict[str, Any]] = []
            orders_rejected: list[dict[str, Any]] = []

            for order in decision.orders:
                price = cycle_prices.get(order.ticker, 0.0)
                if price <= 0:
                    price = get_portfolio_prices([order.ticker]).get(order.ticker, 0.0)
                if price <= 0:
                    orders_rejected.append({"order": order.model_dump(), "why": "no valid price"})
                    continue
                record = portfolio.execute_order(order, price)
                if record:
                    record.id = db.save_trade(record)
                    trades_executed.append(record.model_dump(mode="json"))
                else:
                    orders_rejected.append({"order": order.model_dump(), "why": "physics: insufficient cash/shares"})

            # Standing intents: the new decision replaces the old set
            new_intents: list[dict[str, Any]] = []
            for co in decision.conditional_orders:
                new_intents.append({
                    "kind": "conditional_order", "action": co.action, "ticker": co.ticker,
                    "shares": co.shares, "trigger_type": co.trigger,
                    "trigger_price": co.trigger_price, "reason": co.reason,
                    "expires_at": (now + timedelta(days=co.good_for_days)).isoformat(),
                })
            for wt in decision.wake_triggers:
                new_intents.append({
                    "kind": "wake_trigger", "ticker": wt.ticker,
                    "trigger_type": wt.condition, "trigger_price": wt.price,
                    "reason": "wake me to reassess",
                    "expires_at": (now + timedelta(days=WAKE_TRIGGER_TTL_DAYS)).isoformat(),
                })
            db.replace_intents(name, new_intents)

            # Journal + watchlist + next wakeup: the agent's continuity
            db.save_journal_entry(name, decision.journal, wake_reason=contexts[name]["wake_reason"])
            watchlist = [t for t in contexts[name]["watchlist"] if t not in set(decision.watchlist_remove)]
            watchlist += [t for t in decision.watchlist_add if t not in watchlist]
            sleep_hours = min(max(decision.next_check_hours, MIN_SLEEP_HOURS), MAX_SLEEP_HOURS)
            db.save_agent_state(
                name,
                next_wakeup=(now + timedelta(hours=sleep_hours)).isoformat(),
                watchlist=watchlist[:40],
            )

            db.save_portfolio_state(name, json.dumps(portfolio.to_dict()))
            if all(p.current_price > 0 for p in portfolio.positions.values()):
                db.save_snapshot(name, datetime.now(timezone.utc), portfolio.total_value)

            # Decision log (full auditability, as before)
            try:
                cycle_num = self._tw_cycle_count if market == "tw" else self._cycle_count
                db.save_decision_log(
                    strategy=name,
                    cycle_number=cycle_num,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    pipeline_json=json.dumps(pipeline_data, ensure_ascii=False, default=str),
                    llm_input_json=json.dumps({
                        "wake_reason": contexts[name]["wake_reason"],
                        "market_data_preview": full_report[:2000],
                        "news_preview": news[:1000] if news else "",
                    }, ensure_ascii=False, default=str),
                    llm_output_json=json.dumps({
                        "market_analysis": decision.market_analysis,
                        "reasoning": decision.reasoning,
                        "journal": decision.journal,
                        "orders_proposed": [o.model_dump() for o in decision.orders],
                        "conditional_orders": [c.model_dump() for c in decision.conditional_orders],
                        "wake_triggers": [w.model_dump() for w in decision.wake_triggers],
                        "next_check_hours": decision.next_check_hours,
                    }, ensure_ascii=False, default=str),
                    risk_check_json=json.dumps({"orders_rejected": orders_rejected}, ensure_ascii=False, default=str),
                    execution_json=json.dumps({
                        "trades_executed": trades_executed,
                        "portfolio_after": {
                            "cash": round(portfolio.cash, 2),
                            "total_value": round(portfolio.total_value, 2),
                            "return_pct": round(portfolio.total_return_pct, 2),
                        },
                    }, ensure_ascii=False, default=str),
                )
            except Exception as e:
                logger.warning("Failed to save decision log for %s: %s", name, e)

            results.append({
                "strategy": name,
                "wake_reason": contexts[name]["wake_reason"],
                "analysis": decision.market_analysis,
                "reasoning": decision.reasoning,
                "orders_requested": len(decision.orders),
                "trades_executed": trades_executed,
                "conditional_orders_placed": len(decision.conditional_orders),
                "next_check_hours": decision.next_check_hours,
                "portfolio_value": round(portfolio.total_value, 2),
                "return_pct": round(portfolio.total_return_pct, 2),
            })

        return results

    # ------------------------------------------------------------------
    # Research report (the math layer)
    # ------------------------------------------------------------------

    def _build_research(
        self, market: str, ticker_list: list[str]
    ) -> tuple[str, dict, dict[str, float], dict[str, Any]]:
        """Quant pipeline over the wake universe. Returns
        (full_report, signals, cycle_prices, pipeline_data)."""
        logger.info("[%s] Building research for %d tickers...", market.upper(), len(ticker_list))

        hist_map = fetch_batch_history(ticker_list, "1y")
        cycle_prices = get_portfolio_prices(ticker_list)

        signals = compute_batch_signals(ticker_list, hist_map)
        for t, sig in signals.items():
            if cycle_prices.get(t):
                sig.price = cycle_prices[t]
        signal_report = format_batch_signal_cards(signals)

        factor_scores = {}
        try:
            factor_scores = compute_factor_scores(ticker_list, hist_map)
            factor_report = format_factor_report(factor_scores)
        except Exception as e:
            logger.warning("Factor computation failed: %s", e)
            factor_report = "Factor data unavailable."

        regime = None
        try:
            regime = detect_regime()
            regime_report = (
                f"MARKET REGIME: {regime.current_regime.upper()}\n"
                f"  Probabilities: Bull={regime.regime_probabilities.get('bull', 0):.0%}, "
                f"Bear={regime.regime_probabilities.get('bear', 0):.0%}, "
                f"Crisis={regime.regime_probabilities.get('crisis', 0):.0%}\n"
                f"  {regime.regime_description}"
            )
        except Exception as e:
            logger.warning("Regime detection failed: %s", e)
            regime_report = "Regime data unavailable."

        insider_signals = {}
        insider_report = ""
        try:
            insider_signals = get_insider_signals(ticker_list[:10])
            lines = [
                f"  {'🟢' if sig.signal == 'bullish' else '🔴'} {t}: {sig.signal} (net buys: {sig.net_insider_buys_30d})"
                for t, sig in insider_signals.items() if sig.signal != "neutral"
            ]
            if lines:
                insider_report = "INSIDER TRADING SIGNALS:\n" + "\n".join(lines)
        except Exception as e:
            logger.warning("Insider data failed: %s", e)

        ml_report = ""
        combined_scores = {}
        try:
            regime_scale = regime.position_scale if regime else 1.0
            combined_scores = combine_signals(signals, factor_scores, insider_signals, regime_scale)
            ml_report = format_combined_report(combined_scores)
        except Exception as e:
            logger.warning("ML combiner failed: %s", e)

        earnings = {}
        earnings_report = ""
        try:
            earnings = analyze_earnings_news(ticker_list[:10])
            earnings_report = format_earnings_report(earnings)
        except Exception as e:
            logger.warning("Earnings analysis failed: %s", e)

        anomaly_report = ""
        anomalies = []
        try:
            anomalies = detect_anomalies(signals, factor_scores, insider_signals, earnings)
            anomaly_report = format_anomaly_report(anomalies)
        except Exception as e:
            logger.warning("Anomaly detection failed: %s", e)

        full_report = "\n\n".join(filter(None, [
            anomaly_report, ml_report, regime_report,
            earnings_report, signal_report, factor_report, insider_report,
        ]))

        pipeline_data = {
            "regime": {
                "current": regime.current_regime,
                "probabilities": regime.regime_probabilities,
                "position_scale": regime.position_scale,
                "description": regime.regime_description,
            } if regime else None,
            "top_signals": [
                {
                    "ticker": cs.ticker,
                    "combined_score": round(cs.combined_score, 3),
                    "signal": cs.signal,
                    "rank": cs.rank,
                    "breakdown": {
                        "technical": round(cs.technical_score, 3),
                        "factor": round(cs.factor_score, 3),
                        "insider": round(cs.insider_score, 3),
                    },
                    "suggested_weight": round(cs.suggested_weight, 3),
                    "confidence": round(cs.confidence, 3),
                }
                for cs in sorted(combined_scores.values(), key=lambda x: x.combined_score, reverse=True)
            ],
            "anomalies": [
                {"ticker": a.ticker, "type": a.alert_type, "severity": a.severity, "message": a.message}
                for a in anomalies
            ],
            "tickers_scanned": len(ticker_list),
        }

        return full_report, signals, cycle_prices, pipeline_data

    # ------------------------------------------------------------------
    # Manual triggers (wake everyone now)
    # ------------------------------------------------------------------

    def run_cycle_now(self) -> list[dict[str, Any]]:
        """Force-wake all US agents (manual trigger)."""
        return self._tick("us", force_wake_all=True)

    def run_tw_cycle_now(self) -> list[dict[str, Any]]:
        """Force-wake all TW agents (manual trigger)."""
        return self._tick("tw", force_wake_all=True)


# Singleton scheduler
trading_scheduler = TradingScheduler()
