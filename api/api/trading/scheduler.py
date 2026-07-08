"""Trading scheduler that runs strategy cycles during market hours.

Cron triggers are intentionally broader than the actual sessions; the
exchange-calendar guard in `_run_strategies_by_names` filters pre-open /
post-close fires and holidays.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
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
from api.quant.portfolio_optimizer import optimize_weights
from api.quant.earnings import analyze_earnings_news, format_earnings_report
from api.quant.anomaly import detect_anomalies, format_anomaly_report
from api.quant.position_sizing import calculate_position_size
from api.quant.risk_rules import create_risk_manager, RiskManager
from api.trading.market_hours import is_market_open
from api.trading.models import TradeDecision, TradeOrder
from api.trading.portfolio import STARTING_CAPITAL, SimulatedPortfolio
from api.trading.strategies import ALL_STRATEGIES, TradingStrategy
from api.trading.strategies_tw import ALL_TW_STRATEGIES

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
TW_TZ = ZoneInfo("Asia/Taipei")

TW_STARTING_CAPITAL = 300_000.0


class TradingScheduler:
    """Manages scheduled trading cycles for all strategies."""

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

        # Initialize TW portfolios
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

    def start(self) -> None:
        """Start the scheduler — runs every 30 min during market hours (ET and TW)."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self.initialize()

        # US: Buffett every 1hr, ARK/Balanced every 30min, Momentum/Quant every 15min
        self._scheduler.add_job(
            lambda: self._run_strategies_by_names(["buffett"], self._portfolios, ALL_STRATEGIES),
            CronTrigger(day_of_week="mon-fri", hour="9-15", minute="0", timezone=ET),
            id="us_buffett", replace_existing=True,
        )
        self._scheduler.add_job(
            lambda: self._run_strategies_by_names(["ark", "balanced"], self._portfolios, ALL_STRATEGIES),
            CronTrigger(day_of_week="mon-fri", hour="9-15", minute="0,30", timezone=ET),
            id="us_30min", replace_existing=True,
        )
        self._scheduler.add_job(
            lambda: self._run_strategies_by_names(["aggressive", "quant"], self._portfolios, ALL_STRATEGIES),
            CronTrigger(day_of_week="mon-fri", hour="9-15", minute="0,15,30,45", timezone=ET),
            id="us_15min", replace_existing=True,
        )

        # TW: Same frequency tiers
        self._scheduler.add_job(
            lambda: self._run_strategies_by_names(["tw_buffett"], self._tw_portfolios, ALL_TW_STRATEGIES),
            CronTrigger(day_of_week="mon-fri", hour="9-13", minute="0", timezone=TW_TZ),
            id="tw_buffett", replace_existing=True,
        )
        self._scheduler.add_job(
            lambda: self._run_strategies_by_names(["tw_ark", "tw_balanced"], self._tw_portfolios, ALL_TW_STRATEGIES),
            CronTrigger(day_of_week="mon-fri", hour="9-13", minute="0,30", timezone=TW_TZ),
            id="tw_30min", replace_existing=True,
        )
        self._scheduler.add_job(
            lambda: self._run_strategies_by_names(["tw_aggressive", "tw_quant"], self._tw_portfolios, ALL_TW_STRATEGIES),
            CronTrigger(day_of_week="mon-fri", hour="9-13", minute="0,15,30,45", timezone=TW_TZ),
            id="tw_15min", replace_existing=True,
        )

        self._scheduler.start()
        self._running = True
        logger.info("Trading scheduler started (US + TW)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("Trading scheduler stopped")

    def get_next_run_time(self) -> str | None:
        """Get the next scheduled US run time (earliest of all US jobs)."""
        times = []
        for jid in ["us_buffett", "us_30min", "us_15min"]:
            job = self._scheduler.get_job(jid)
            if job and job.next_run_time:
                times.append(job.next_run_time)
        return min(times).isoformat() if times else None

    def get_tw_next_run_time(self) -> str | None:
        """Get the next scheduled TW run time."""
        times = []
        for jid in ["tw_buffett", "tw_30min", "tw_15min"]:
            job = self._scheduler.get_job(jid)
            if job and job.next_run_time:
                times.append(job.next_run_time)
        return min(times).isoformat() if times else None

    def get_portfolios(self) -> dict[str, SimulatedPortfolio]:
        return dict(self._portfolios)

    def get_tw_portfolios(self) -> dict[str, SimulatedPortfolio]:
        return dict(self._tw_portfolios)

    def get_portfolio(self, strategy: str) -> SimulatedPortfolio | None:
        return self._portfolios.get(strategy)

    def get_tw_portfolio(self, strategy: str) -> SimulatedPortfolio | None:
        return self._tw_portfolios.get(strategy)

    def _run_strategies_by_names(
        self,
        names: list[str],
        portfolios: dict[str, SimulatedPortfolio],
        all_strategies: list,
    ) -> list[dict[str, Any]]:
        """Run a subset of strategies by name. Used by frequency-tiered scheduler jobs."""
        strategy_map = {s.name: s for s in all_strategies}
        subset = [strategy_map[n] for n in names if n in strategy_map]
        if not subset:
            return []

        market = subset[0].market if hasattr(subset[0], 'market') else 'us'
        lock = self._tw_lock if market == 'tw' else self._lock

        # Cron windows are broader than actual sessions (e.g. 9:00 ET fires
        # pre-open); the calendar guard also covers exchange holidays.
        if not is_market_open(market):
            logger.info("[%s] Market closed — skipping scheduled cycle for %s", market.upper(), names)
            return []

        with lock:
            logger.info("Running %s strategies: %s", market.upper(), [s.name for s in subset])
            return self._run_subset(subset, portfolios)

    def _run_subset(self, strategies: list, portfolios: dict) -> list[dict[str, Any]]:
        """Execute strategies with hybrid architecture: Math → LLM → Risk Rules.

        Flow:
        ┌─────────────────────────────────────────────────────┐
        │ 1. MATH ENGINE: compute signals + scores            │
        │ 2. LLM: decide trades using signal cards + news     │
        │ 3. RISK RULES: validate + enforce hard limits       │
        │ 4. EXECUTE: fill orders at market price              │
        └─────────────────────────────────────────────────────┘
        """
        market = strategies[0].market if hasattr(strategies[0], 'market') else 'us'

        # ── Layer 1: MATH ENGINE ───────────────────────────────
        # Compute quant signals for all relevant tickers
        all_tickers: set[str] = set()
        for s in strategies:
            if s.watchlist:
                all_tickers.update(s.watchlist[:15])  # Top 15 from watchlist
            portfolio = portfolios.get(s.name)
            if portfolio:
                all_tickers.update(portfolio.positions.keys())
        # Add default watchlist if empty
        if not all_tickers:
            all_tickers = {"NVDA", "TSLA", "AAPL", "MSFT", "META", "GOOGL"}

        ticker_list = list(all_tickers)
        logger.info("[%s] Computing quant signals for %d tickers...", market.upper(), len(ticker_list))

        # One batch download reused by signals + factors (vs 2 fetches/ticker)
        hist_map = fetch_batch_history(ticker_list, "1y")

        # One canonical price map per cycle: the LLM report, stop-loss checks,
        # and order fills all use the same prices (they used to diverge).
        cycle_prices = get_portfolio_prices(ticker_list)

        # Technical signals (RSI, MACD, Bollinger, etc.)
        signals = compute_batch_signals(ticker_list, hist_map)
        for t, sig in signals.items():
            if cycle_prices.get(t):
                sig.price = cycle_prices[t]
        signal_report = format_batch_signal_cards(signals)

        # Initialize variables (may be overwritten in try blocks)
        factor_scores = {}
        insider_signals = {}
        combined_scores = {}
        anomalies = []
        earnings = {}
        regime = None

        # Factor model (Value, Momentum, Quality, Size, Volatility)
        try:
            factor_scores = compute_factor_scores(ticker_list, hist_map)
            factor_report = format_factor_report(factor_scores)
        except Exception as e:
            logger.warning("Factor computation failed: %s", e)
            factor_report = "Factor data unavailable."

        # Market regime detection (HMM)
        try:
            regime = detect_regime()
            regime_report = (
                f"MARKET REGIME: {regime.current_regime.upper()}\n"
                f"  Probabilities: Bull={regime.regime_probabilities.get('bull', 0):.0%}, "
                f"Bear={regime.regime_probabilities.get('bear', 0):.0%}, "
                f"Crisis={regime.regime_probabilities.get('crisis', 0):.0%}\n"
                f"  Position Scale: {regime.position_scale:.0%} (reduce all positions by this factor)\n"
                f"  {regime.regime_description}"
            )
        except Exception as e:
            logger.warning("Regime detection failed: %s", e)
            regime = None
            regime_report = "Regime data unavailable."

        # Insider trading signals
        try:
            insider_signals = get_insider_signals(ticker_list[:10])
            insider_lines = ["INSIDER TRADING SIGNALS:"]
            for t, sig in insider_signals.items():
                if sig.signal != "neutral":
                    emoji = "🟢" if sig.signal == "bullish" else "🔴"
                    insider_lines.append(f"  {emoji} {t}: {sig.signal} (net buys: {sig.net_insider_buys_30d})")
            insider_report = "\n".join(insider_lines) if len(insider_lines) > 1 else ""
        except Exception as e:
            logger.warning("Insider data failed: %s", e)
            insider_report = ""

        # ML Signal Combiner — merge all signals into ranked composite
        try:
            regime_scale = regime.position_scale if regime else 1.0
            _factors = factor_scores if factor_report != "Factor data unavailable." else {}
            _insiders = insider_signals if insider_report else {}
            combined_scores = combine_signals(signals, _factors, _insiders, regime_scale)
            ml_report = format_combined_report(combined_scores)

            # Portfolio optimizer — suggested weights
            vols = {t: s.daily_volatility for t, s in signals.items() if s.daily_volatility}
            score_dict = {t: cs.combined_score for t, cs in combined_scores.items()}
            optimal = optimize_weights(list(combined_scores.keys()), score_dict, vols, regime_scale=regime_scale)
            weight_lines = ["OPTIMAL PORTFOLIO WEIGHTS:"]
            for t, w in sorted(optimal.weights.items(), key=lambda x: -x[1]):
                if w > 0.01:
                    weight_lines.append(f"  {t}: {w:.1%}")
            weight_lines.append(f"  Cash: {optimal.cash_weight:.1%}")
            weight_report = "\n".join(weight_lines)
        except Exception as e:
            logger.warning("ML combiner/optimizer failed: %s", e)
            ml_report = ""
            weight_report = ""

        # Earnings analysis
        try:
            earnings = analyze_earnings_news(ticker_list[:10])
            earnings_report = format_earnings_report(earnings)
        except Exception as e:
            logger.warning("Earnings analysis failed: %s", e)
            earnings = {}
            earnings_report = ""

        # Anomaly detection
        try:
            anomalies = detect_anomalies(signals, factor_scores, insider_signals, earnings)
            anomaly_report = format_anomaly_report(anomalies)
        except Exception as e:
            logger.warning("Anomaly detection failed: %s", e)
            anomaly_report = ""

        # ── Build pipeline_data for decision logging ───────────
        _top_signals = [
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
        ]

        _anomalies_data: list[dict[str, Any]] = [
            {"ticker": a.ticker, "type": a.alert_type, "severity": a.severity, "message": a.message}
            for a in anomalies
        ]

        _earnings_data: list[dict[str, Any]] = [
            {"ticker": t, "sentiment": e.sentiment, "guidance": e.forward_guidance}
            for t, e in earnings.items() if e.has_recent_earnings
        ]

        pipeline_data = {
            "regime": {
                "current": regime.current_regime,
                "probabilities": regime.regime_probabilities,
                "position_scale": regime.position_scale,
                "description": regime.regime_description,
            } if regime else None,
            "top_signals": _top_signals,
            "anomalies": _anomalies_data,
            "earnings": _earnings_data,
            "tickers_scanned": len(ticker_list),
        }

        # Combine all reports into market data for LLM
        news_tickers = ticker_list[:6]
        news = get_news_summary(news_tickers)

        full_report = "\n\n".join(filter(None, [
            anomaly_report,   # Anomaly alerts FIRST (most urgent)
            ml_report,        # Combined ranking
            weight_report,    # Suggested allocation
            regime_report,    # Market regime
            earnings_report,  # Earnings events
            signal_report,    # Detailed technical signals
            factor_report,    # Factor scores
            insider_report,   # Insider data
        ]))

        strategy_market_data: dict[str, str] = {}
        for strategy in strategies:
            strategy_market_data[strategy.name] = full_report

        # Update prices for held positions (held tickers are part of the
        # cycle universe, so cycle_prices covers them)
        for s in strategies:
            portfolio = portfolios.get(s.name)
            if portfolio:
                portfolio.update_prices(cycle_prices)

        # ── Check portfolio health (stop losses + daily loss halt) ─────
        tz = TW_TZ if market == 'tw' else ET
        day_start_utc = (
            datetime.now(tz)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc)
        )
        daily_halted: dict[str, bool] = {}
        for strategy in strategies:
            portfolio = portfolios[strategy.name]
            style = strategy.style if hasattr(strategy, 'style') else 'balanced'
            risk_mgr = create_risk_manager(style)
            positions_dict = {
                t: {"shares": p.shares, "avg_cost": p.avg_cost, "current_price": p.current_price}
                for t, p in portfolio.positions.items()
            }
            health = risk_mgr.check_portfolio_health(positions_dict)
            # Execute forced sells (stop losses)
            for forced in health.forced_sells:
                ticker = forced["ticker"]
                shares = forced["shares"]
                price = cycle_prices.get(ticker, 0)
                if price > 0 and shares > 0:
                    order = TradeOrder(action="SELL", ticker=ticker, shares=shares, reason=forced["reason"])
                    record = portfolio.execute_order(order, price)
                    if record:
                        record.id = db.save_trade(record)
                        logger.warning("[%s] FORCED SELL %s: %s", strategy.name, ticker, forced["reason"])

            # Daily-loss circuit breaker: measured from today's first snapshot
            # (exchange-local day). SELLs stay allowed; BUYs are blocked below.
            day_start_value = db.get_first_snapshot_since(strategy.name, day_start_utc.isoformat())
            daily = risk_mgr.check_daily_loss(day_start_value, portfolio.total_value)
            daily_halted[strategy.name] = not daily.approved
            if not daily.approved:
                logger.warning(
                    "[%s] DAILY LOSS HALT: %s",
                    strategy.name, "; ".join(v.message for v in daily.violations),
                )

        # ── Layer 2: LLM DECISIONS ─────────────────────────────
        decisions: dict[str, TradeDecision] = {}
        with ThreadPoolExecutor(max_workers=len(strategies)) as executor:
            futures = {}
            for strategy in strategies:
                portfolio = portfolios[strategy.name]
                state = portfolio.get_state()
                future = executor.submit(
                    self._run_strategy, strategy, state,
                    strategy_market_data[strategy.name], news,
                )
                futures[future] = strategy.name
            for future in as_completed(futures):
                name = futures[future]
                try:
                    decisions[name] = future.result()
                except Exception as e:
                    logger.error("Strategy %s failed: %s", name, e, exc_info=True)

        # ── Layer 3: RISK RULES + EXECUTE ──────────────────────
        results: list[dict[str, Any]] = []
        for strategy_name, decision in decisions.items():
            strategy = next((s for s in strategies if s.name == strategy_name), None)
            portfolio = portfolios[strategy_name]
            style = strategy.style if strategy and hasattr(strategy, 'style') else 'balanced'
            risk_mgr = create_risk_manager(style)
            trades_executed = []
            trades_blocked = []
            trades_this_cycle = 0
            risk_check_data: dict[str, list] = {"orders_approved": [], "orders_blocked": []}

            for order in decision.orders:
                # Fill at the same price the LLM saw; fall back to a direct
                # fetch only for tickers outside the cycle universe (e.g. a
                # SELL of a position the LLM knows but wasn't scanned)
                price = cycle_prices.get(order.ticker, 0.0)
                if price <= 0:
                    price = get_portfolio_prices([order.ticker]).get(order.ticker, 0.0)
                if price <= 0:
                    continue

                if order.action == "BUY":
                    original_shares = order.shares

                    # Hard gates the LLM cannot bypass: daily-loss halt + watchlist
                    block_reason = None
                    if daily_halted.get(strategy_name):
                        block_reason = "DAILY_LOSS_LIMIT: buying halted for the rest of the day"
                    elif strategy and strategy.watchlist is not None and order.ticker not in strategy.watchlist:
                        block_reason = f"WATCHLIST: {order.ticker} is not on this strategy's watchlist"
                    if block_reason:
                        trades_blocked.append(f"BLOCKED BUY {order.ticker}: {block_reason}")
                        risk_check_data["orders_blocked"].append({
                            "action": order.action, "ticker": order.ticker,
                            "shares": order.shares, "reason": block_reason,
                        })
                        logger.info("[%s] BLOCKED: BUY %s — %s", strategy_name, order.ticker, block_reason)
                        continue

                    # Risk check before buying
                    positions_dict = {
                        t: {"shares": p.shares, "avg_cost": p.avg_cost, "current_price": p.current_price}
                        for t, p in portfolio.positions.items()
                    }
                    check = risk_mgr.check_buy_order(
                        ticker=order.ticker,
                        shares=order.shares,
                        price=price,
                        cash=portfolio.cash,
                        portfolio_value=portfolio.total_value,
                        current_positions=positions_dict,
                        trades_this_cycle=trades_this_cycle,
                    )

                    if not check.approved:
                        reason = "; ".join(v.message for v in check.violations)
                        trades_blocked.append(f"BLOCKED {order.action} {order.ticker}: {reason}")
                        risk_check_data["orders_blocked"].append({
                            "action": order.action, "ticker": order.ticker,
                            "shares": order.shares, "reason": reason,
                        })
                        logger.info("[%s] BLOCKED: %s %s — %s", strategy_name, order.action, order.ticker, reason)
                        continue

                    # Track adjustments for decision log
                    adjustments: list[str] = []

                    # Adjust shares if risk rules reduced the size
                    if check.adjusted_shares is not None:
                        adjustments.append(f"Risk rules reduced from {original_shares} to {check.adjusted_shares}")
                        order = TradeOrder(
                            action=order.action, ticker=order.ticker,
                            shares=check.adjusted_shares, reason=order.reason,
                        )

                    # Apply position sizing from quant engine
                    sig = signals.get(order.ticker)
                    if sig and sig.atr_14:
                        sizing = calculate_position_size(
                            portfolio_value=portfolio.total_value,
                            cash=portfolio.cash,
                            entry_price=price,
                            atr=sig.atr_14,
                        )
                        if sizing.risk_based_shares < order.shares:
                            adjustments.append(f"Kelly sized to {sizing.risk_based_shares}")
                            order = TradeOrder(
                                action=order.action, ticker=order.ticker,
                                shares=sizing.risk_based_shares, reason=order.reason,
                            )

                    # Apply regime-based position scaling
                    if regime and regime.position_scale < 1.0 and order.action == "BUY":
                        scaled_shares = max(1, int(order.shares * regime.position_scale))
                        if scaled_shares < order.shares:
                            adjustments.append(f"Regime scaled to {regime.position_scale:.0%}")
                            order = TradeOrder(
                                action=order.action, ticker=order.ticker,
                                shares=scaled_shares,
                                reason=order.reason + f" [regime-scaled to {regime.position_scale:.0%}]",
                            )

                    risk_check_data["orders_approved"].append({
                        "action": order.action, "ticker": order.ticker,
                        "shares": order.shares, "original_shares": original_shares,
                        "adjustments": adjustments,
                    })

                record = portfolio.execute_order(order, price)
                if record:
                    record.id = db.save_trade(record)
                    trades_executed.append(record.model_dump(mode="json"))
                    trades_this_cycle += 1

            db.save_portfolio_state(strategy_name, json.dumps(portfolio.to_dict()))
            # Skip the snapshot if any held position has no valid price —
            # a failed quote would otherwise record a fake portfolio collapse.
            if all(p.current_price > 0 for p in portfolio.positions.values()):
                db.save_snapshot(strategy_name, datetime.now(timezone.utc), portfolio.total_value)
            else:
                bad = [t for t, p in portfolio.positions.items() if p.current_price <= 0]
                logger.warning("[%s] Skipping snapshot: missing prices for %s", strategy_name, bad)

            # Save decision log
            llm_input_data = {
                "market_data_preview": strategy_market_data.get(strategy_name, "")[:2000],
                "news_preview": news[:1000] if news else "",
            }
            llm_output_data = {
                "market_analysis": decision.market_analysis,
                "reasoning": decision.reasoning,
                "orders_proposed": [
                    {"action": o.action, "ticker": o.ticker, "shares": o.shares, "reason": o.reason}
                    for o in decision.orders
                ],
            }
            execution_data = {
                "trades_executed": trades_executed,
                "portfolio_after": {
                    "cash": round(portfolio.cash, 2),
                    "total_value": round(portfolio.total_value, 2),
                    "return_pct": round(portfolio.total_return_pct, 2),
                },
            }

            try:
                cycle_num = self._tw_cycle_count if market == 'tw' else self._cycle_count
                db.save_decision_log(
                    strategy=strategy_name,
                    cycle_number=cycle_num,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    pipeline_json=json.dumps(pipeline_data, ensure_ascii=False, default=str),
                    llm_input_json=json.dumps(llm_input_data, ensure_ascii=False, default=str),
                    llm_output_json=json.dumps(llm_output_data, ensure_ascii=False, default=str),
                    risk_check_json=json.dumps(risk_check_data, ensure_ascii=False, default=str),
                    execution_json=json.dumps(execution_data, ensure_ascii=False, default=str),
                )
            except Exception as e:
                logger.warning("Failed to save decision log for %s: %s", strategy_name, e)

            results.append({
                "strategy": strategy_name,
                "analysis": decision.market_analysis,
                "reasoning": decision.reasoning,
                "orders_requested": len(decision.orders),
                "trades_executed": trades_executed,
                "trades_blocked": trades_blocked,
                "portfolio_value": round(portfolio.total_value, 2),
                "return_pct": round(portfolio.total_return_pct, 2),
            })

        if market == 'tw':
            self._tw_cycle_count += 1
            self._last_tw_cycle_results = results
        else:
            self._cycle_count += 1
            self._last_cycle_results = results

        return results

    def run_cycle_now(self) -> list[dict[str, Any]]:
        """Manually trigger a US cycle — uses full quant pipeline + decision logging."""
        if not self._portfolios:
            self.initialize()
        with self._lock:
            return self._run_subset(ALL_STRATEGIES, self._portfolios)

    def run_tw_cycle_now(self) -> list[dict[str, Any]]:
        """Manually trigger a TW cycle — uses full quant pipeline + decision logging."""
        if not self._tw_portfolios:
            self.initialize()
        with self._tw_lock:
            return self._run_subset(ALL_TW_STRATEGIES, self._tw_portfolios)

    def _run_strategy(
        self,
        strategy: TradingStrategy,
        state: Any,
        market_data: str,
        news: str,
    ) -> TradeDecision:
        """Run a single strategy's decide method."""
        return strategy.decide(self._llm, state, market_data, news)


# Singleton scheduler
trading_scheduler = TradingScheduler()
