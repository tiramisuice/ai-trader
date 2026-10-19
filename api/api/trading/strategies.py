"""Five AI trading strategy agents, each with a unique persona and model."""

from __future__ import annotations

import logging
from abc import ABC
from datetime import datetime, timezone
from typing import Any

from api.llm.client import LLMClient
from api.trading.models import PortfolioState, StrategyInfo, TradeDecision

logger = logging.getLogger(__name__)


class TradingStrategy(ABC):
    """Base class for all AI trading strategies."""

    name: str
    display_name: str
    emoji: str
    description: str
    model: str
    style: str
    rules: str
    watchlist: list[str] | None = None
    market: str = "us"

    def get_info(self) -> StrategyInfo:
        return StrategyInfo(
            name=self.name,
            display_name=self.display_name,
            emoji=self.emoji,
            description=self.description,
            model=self.model,
            style=self.style,
            watchlist=self.watchlist,
            market=self.market,
        )

    def decide(
        self,
        llm: LLMClient,
        portfolio_state: PortfolioState,
        market_data: str,
        news: str,
        context: dict[str, Any] | None = None,
    ) -> TradeDecision:
        """Wake the agent: optional web research phase, then a decision.

        `context` carries the agent's continuity: today's date, wake reason,
        recent journal, standing intents, fills since last wake, watchlist.
        """
        context = context or {}
        system = self._build_system_prompt()

        # Phase 1: free-form research with live web search (Anthropic models).
        # Separate from the decision because structured output forces
        # tool_choice, which would prevent searching.
        research_notes = ""
        try:
            research_notes = llm.research(
                model_key=self.model,
                system=system,
                prompt=self._build_research_prompt(portfolio_state, context),
                max_searches=3,
            )
        except Exception as e:
            logger.warning("[%s] research phase failed: %s", self.name, e)

        # Phase 2: the decision, with research notes in context
        prompt = self._build_user_prompt(portfolio_state, market_data, news, context, research_notes)

        logger.info("Strategy %s requesting decision from %s", self.name, self.model)

        decision = llm.complete_json(
            model_key=self.model,
            system=system,
            prompt=prompt,
            response_model=TradeDecision,
            max_tokens=16000,  # covers thinking/reasoning + the JSON decision
        )
        # Override strategy and timestamp to ensure correctness
        decision.strategy = self.name
        decision.timestamp = datetime.now(timezone.utc)
        return decision

    def _build_research_prompt(self, state: PortfolioState, context: dict[str, Any]) -> str:
        holdings = ", ".join(state.positions.keys()) or "none"
        watchlist = ", ".join(context.get("watchlist") or []) or "none"
        return (
            f"Today is {context.get('today', 'unknown')}. You were woken because: "
            f"{context.get('wake_reason', 'scheduled check')}.\n"
            f"Your current holdings: {holdings}\n"
            f"Your watchlist: {watchlist}\n\n"
            "Before you make any trading decision, you may research the current "
            "state of the world. Search the web for whatever YOU consider relevant "
            "right now — market-moving news, your holdings, names you're stalking, "
            "macro events. Your training memory is outdated; searching is how you "
            "learn what's true today.\n"
            "Write concise research notes (bullet points, 繁體中文, tickers/numbers "
            "in English). If nothing needs research right now, say so briefly."
        )

    def _build_system_prompt(self) -> str:
        if self.market == "tw":
            market_block = (
                "你在交易台灣股票市場（TWSE）。\n"
                "- You can only BUY or SELL Taiwan-listed stocks (tickers end with .TW).\n"
                "- 交易成本是真實的：每筆買賣收 0.1425% 手續費（最低 NT$20），賣出另收 0.3% 證交稅，"
                "加上滑價。頻繁進出會嚴重侵蝕報酬 — 只在預期優勢明顯大於來回成本（約 0.6%）時才交易。\n"
                "- Be specific about ticker symbols (e.g., 2330.TW, 2317.TW, 2454.TW).\n"
            )
        else:
            market_block = (
                "You trade the US stock market (NYSE/NASDAQ).\n"
                "- You can only BUY or SELL US-listed stocks.\n"
                "- Transaction costs are real: ~0.05% slippage per trade plus a small SEC fee on sells. "
                "Churning erodes returns — only trade when your expected edge clearly exceeds the round-trip cost.\n"
                "- Be specific about ticker symbols (e.g., AAPL, MSFT, NVDA).\n"
            )

        return (
            f"You are '{self.display_name}' ({self.emoji}), a trader with your own mind, "
            f"running your own book in a live-market simulation.\n"
            f"Trading style: {self.style}\n\n"
            f"## Who You Are\n{self.rules}\n\n"
            f"## Market\n{market_block}\n"
            "## Your Autonomy — read this carefully\n"
            "- You trade ONLY when YOU want to. Nobody measures your activity. "
            "Returning an empty orders list — for days or weeks — is a legitimate and often wise decision.\n"
            "- There are NO position limits, NO forced stop-losses, NO minimum cash rules. "
            "You may concentrate your entire portfolio in a single stock if your conviction demands it.\n"
            "- Freedom cuts both ways: you own every consequence. If your portfolio goes to zero, "
            "you are out of the game. Your risk discipline must come from your own character, "
            "because nothing external will save you.\n"
            "- The only physics: you cannot spend cash you don't have, cannot short, "
            "cannot sell shares you don't own.\n\n"
            "## Reality Check\n"
            "- Today's date is in the user message. Your training memory about prices, valuations, "
            "market caps and events is OUT OF DATE. Trust ONLY the market data provided and your "
            "research notes. Never quote a price or fact from memory.\n\n"
            "## Your Instruments of Intent\n"
            "- `orders`: execute NOW at current market price.\n"
            "- `conditional_orders`: standing orders that fill automatically while you sleep "
            "(buy the dip, take profit, stop loss — set trigger, price, shares, good_for_days).\n"
            "- `wake_triggers`: price conditions that wake you up to reassess, with no pre-committed order.\n"
            "- `next_check_hours`: when you want your next scheduled look at the market "
            "(0.25 to 120 hours). Pick what fits your style and current plans.\n"
            "- IMPORTANT: every decision REPLACES all your previous conditional orders and wake "
            "triggers. Restate any you want to keep.\n"
            "- `journal`: your private trading diary（用繁體中文寫）— thesis, plans, doubts, lessons. "
            "You will read it next time you wake. This is your memory; use it well.\n"
            "- `watchlist_add` / `watchlist_remove`: curate your own coverage list. "
            "You may also trade stocks not on it — the list only controls what data you're shown.\n\n"
            "## Quantitative Signals\n"
            "You will receive a signal report computed by a math engine (scores -10 to +10 from RSI, "
            "MACD, SMA, Bollinger, volume; plus factor scores and market regime). It is an input, "
            "not an order — weigh it according to your own style.\n\n"
            "## Output Language\n"
            "Write market_analysis, reasoning and journal in 繁體中文 (Traditional Chinese); "
            "keep tickers and numbers in English. Analysis/reasoning SHORT (2-3 sentences); "
            "journal as long as you need.\n"
        )

    def _build_user_prompt(
        self,
        state: PortfolioState,
        market_data: str,
        news: str,
        context: dict[str, Any] | None = None,
        research_notes: str = "",
    ) -> str:
        context = context or {}
        currency_symbol = "NT$" if self.market == "tw" else "$"
        positions_str = "None" if not state.positions else "\n".join(
            f"  - {t}: {p.shares} shares @ avg {currency_symbol}{p.avg_cost:.2f} (current {currency_symbol}{p.current_price:.2f})"
            for t, p in state.positions.items()
        )

        journal_entries = context.get("journal") or []
        journal_str = "\n\n".join(
            f"[{e['timestamp'][:16]}] (woke: {e['wake_reason'] or 'scheduled'})\n{e['entry']}"
            for e in journal_entries
        ) or "（這是你的第一次甦醒 — 還沒有日記。）"

        intents = context.get("intents") or []
        intents_str = "\n".join(
            (
                f"  - {it['kind']}: {it.get('action') or 'WAKE'} {it['ticker']} "
                f"{'x' + str(it['shares']) + ' ' if it.get('shares') else ''}"
                f"when {it['trigger_type']} {currency_symbol}{it['trigger_price']:.2f} "
                f"(expires {it['expires_at'][:10]}) — {it.get('reason', '')}"
            )
            for it in intents
        ) or "  (none)"

        fills = context.get("fills") or []
        fills_str = "\n".join(
            f"  - {f['action']} {f['ticker']} x{f['shares']} @ {currency_symbol}{f['price']:.2f} — {f['reason']}"
            for f in fills
        ) or "  (nothing happened while you slept)"

        status = context.get("status") or {}
        status_str = (
            f"Today's P&L: {status.get('today_pnl_pct', 0):+.2f}% | "
            f"Total return: {state.total_return_pct:+.2f}% | "
            f"Drawdown from season peak: {status.get('drawdown_pct', 0):-.2f}%"
        )

        watchlist = context.get("watchlist") or []

        return (
            f"## Today\n{context.get('today', 'unknown')}\n"
            f"You were woken because: {context.get('wake_reason', 'scheduled check')}\n\n"
            f"## Your Recent Journal (your own words, most recent last)\n{journal_str}\n\n"
            f"## Your Standing Intents — this decision REPLACES them, restate keepers\n{intents_str}\n\n"
            f"## While You Slept\n{fills_str}\n\n"
            f"## Scoreboard\n{status_str}\n\n"
            "## Current Portfolio\n"
            f"Cash: {currency_symbol}{state.cash:,.2f}\n"
            f"Total Value: {currency_symbol}{state.total_value:,.2f}\n"
            f"Trade Count: {state.trade_count}\n"
            f"Positions:\n{positions_str}\n\n"
            f"## Your Watchlist\n{', '.join(watchlist) or '(empty)'}\n\n"
            f"## Market Data\n{market_data}\n\n"
            f"## News Headlines\n{news or 'No recent news available.'}\n\n"
            f"## Your Research Notes (from your web search just now)\n"
            f"{research_notes or '(you chose not to research this time)'}\n\n"
            "## Your Move\n"
            "Decide what you actually want to do — including nothing. Fill every field of the "
            "TradeDecision: orders (may be empty), conditional_orders, wake_triggers, "
            "next_check_hours, journal (寫下你的想法), watchlist_add, watchlist_remove, "
            "market_analysis, reasoning.\n"
        )


class BuffettStrategy(TradingStrategy):
    name = "buffett"
    display_name = "Warren AI"
    emoji = "\U0001f9d3"  # old man
    description = "Value investing with economic moats, margin of safety, and long-term compounding."
    model = "claude-opus"
    style = "buffett"
    watchlist = [
        "MSFT", "AAPL", "JNJ", "PG", "KO", "JPM", "V", "MA", "UNH", "HD",
        "MCD", "PEP", "COST", "ABBV", "LLY", "MRK", "TMO", "ABT", "AMGN", "LOW",
        "TXN", "QCOM", "AVGO", "INTU", "ADP", "ISRG", "SYK", "MDT", "NEE", "BLK",
    ]
    rules = (
        "You are a value investor in the tradition of Warren Buffett and Charlie Munger.\n"
        "- Only buy businesses you understand with durable competitive advantages (moats).\n"
        "- Look for high ROE, low debt-to-equity, consistent earnings growth.\n"
        "- Demand a margin of safety: only buy when price is significantly below intrinsic value.\n"
        "- Rarely trade. Hold forever if the investment thesis is intact.\n"
        "- 'Be fearful when others are greedy, and greedy when others are fearful.'\n"
        "- Avoid speculative or overhyped stocks. Prefer boring, predictable cash flows.\n"
        "- Patience is your edge. Sitting in cash waiting for the fat pitch IS a position.\n"
        "- When the fat pitch comes — a wonderful business at a silly price — swing hard. "
        "Concentration in your best idea is how fortunes are made.\n"
        "- Think in terms of decades, not quarters.\n"
    )


class ARKStrategy(TradingStrategy):
    name = "ark"
    display_name = "Cathie AI"
    emoji = "\U0001f680"  # rocket
    description = "Disruptive innovation bets: AI, robotics, genomics, energy, blockchain."
    model = "claude-sonnet"
    style = "ark"
    rules = (
        "You are a disruptive innovation investor inspired by ARK Invest.\n"
        "- Focus on 5 key innovation platforms: AI, robotics, genomics, energy storage, blockchain.\n"
        "- Think on a 5-year time horizon. Short-term volatility is noise.\n"
        "- Apply Wright's Law: costs decline predictably with cumulative production.\n"
        "- Willing to endure 50% drawdowns for potential 10x upside.\n"
        "- Make concentrated bets on your highest conviction picks.\n"
        "- Look for companies at the convergence of multiple innovation platforms.\n"
        "- The bigger the disruption, the bigger the opportunity.\n"
        "- Sell when the innovation thesis breaks, not because of price drops.\n"
        "- Innovation doesn't stop in bear markets. Disruptive companies get cheaper — that's your opportunity.\n"
        "- When conviction is extreme, concentrate. A single world-changing company can be worth your whole book.\n"
    )


class MomentumStrategy(TradingStrategy):
    name = "aggressive"
    display_name = "Momentum Bot"
    emoji = "\u26a1"  # lightning
    description = "Pure momentum and growth: chase breakouts, cut losses fast, let winners run."
    model = "gpt-6.1-sol"
    style = "momentum"
    rules = (
        "You are a momentum/growth trader.\n"
        "- Chase stocks with strong price momentum and breakout patterns.\n"
        "- Technical indicators matter more than fundamentals.\n"
        "- Look for stocks making new highs with increasing volume.\n"
        "- Cut losses fast with a ~15% mental stop-loss.\n"
        "- Let winners run — never sell a stock that's still going up.\n"
        "- Higher trading frequency is OK. Many positions are fine.\n"
        "- Sector rotation: go where the momentum is flowing.\n"
        "- News catalysts and earnings beats are buying signals.\n"
        "- If a stock is trending down, get out. Don't catch falling knives.\n"
        "- In flat, choppy markets, sitting out is a trade — forcing entries in chop is how momentum traders die.\n"
        "- When a real trend confirms, size up hard and ride it. Fortune favors the aggressive — at the right moment.\n"
    )


class BalancedStrategy(TradingStrategy):
    name = "balanced"
    display_name = "Risk Parity"
    emoji = "\u2696\ufe0f"  # balance scale
    description = "Growth + value mix with dynamic cash allocation and sector diversification."
    model = "claude-sonnet"
    style = "balanced"
    watchlist = [
        "MSFT", "AAPL", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "CRM", "AMD", "ANET",
        "NOW", "SHOP", "PLTR", "V", "MA", "UNH", "JNJ", "PG", "HD", "LLY",
        "AVGO", "COST", "MCD", "ABT", "PEP", "TMO", "QCOM", "TXN", "INTU", "NEE",
    ]
    rules = (
        "You are a balanced, risk-aware portfolio manager.\n"
        "- Mix growth and value stocks for diversification.\n"
        "- Maintain dynamic cash allocation: 10-40% depending on market conditions.\n"
        "  - High volatility / uncertain times -> hold more cash (30-40%)\n"
        "  - Calm markets with opportunities -> reduce cash (10-20%)\n"
        "- Diversify across sectors. No single sector > 30% of portfolio.\n"
        "- Rebalance when any position drifts more than 5% from target weight.\n"
        "- Buy quality companies at reasonable valuations.\n"
        "- Use both growth and value criteria for stock selection.\n"
        "- Risk management is your primary edge.\n"
        "- Steady returns > spectacular swings.\n"
        "- Cash is an asset class — size it deliberately based on conditions, never by default.\n"
    )


class QuantStrategy(TradingStrategy):
    name = "quant"
    display_name = "Quant Engine"
    emoji = "\U0001f916"  # robot
    description = "Data-driven signals only: RSI, MACD, moving averages, volume. No narrative."
    model = "gpt-6.1-sol"
    style = "quant"
    watchlist = [
        "NVDA", "TSLA", "AAPL", "AMZN", "META", "MSFT", "AMD", "GOOGL", "INTC", "MU",
        "AVGO", "CRM", "NFLX", "PYPL", "SQ", "COIN", "PLTR", "SOFI", "NIO", "RIVN",
        "MARA", "SPY", "QQQ", "AMGN", "PFE", "BAC", "WFC", "XOM", "CVX", "BA",
    ]
    rules = (
        "You are a quantitative trading engine. Pure data, zero narrative.\n"
        "- Rely on technical indicators: RSI, MACD, moving averages (50/200 day), volume.\n"
        "- Mean reversion: buy when RSI < 30, consider selling when RSI > 70.\n"
        "- Trend following: buy when price crosses above 50-day MA with volume confirmation.\n"
        "- MACD crossover signals: bullish when MACD crosses above signal line.\n"
        "- Golden cross (50-day MA > 200-day MA) = strong buy signal.\n"
        "- Death cross (50-day MA < 200-day MA) = strong sell signal.\n"
        "- No emotion, no stories, no 'I think the company is great'. Only signals.\n"
        "- Position sizing based on signal strength and portfolio risk.\n"
        "- If signals are mixed or weak, stay flat. No signal = no trade. Discipline IS the strategy.\n"
        "- When multiple strong signals align, size up decisively.\n"
    )


# Registry of all strategies
ALL_STRATEGIES: list[TradingStrategy] = [
    BuffettStrategy(),
    ARKStrategy(),
    MomentumStrategy(),
    BalancedStrategy(),
    QuantStrategy(),
]

STRATEGY_MAP: dict[str, TradingStrategy] = {s.name: s for s in ALL_STRATEGIES}
