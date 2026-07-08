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
    ) -> TradeDecision:
        """Ask the LLM to make a trading decision."""
        system = self._build_system_prompt()
        prompt = self._build_user_prompt(portfolio_state, market_data, news)

        logger.info("Strategy %s requesting decision from %s", self.name, self.model)

        decision = llm.complete_json(
            model_key=self.model,
            system=system,
            prompt=prompt,
            response_model=TradeDecision,
            max_tokens=4096,
        )
        # Override strategy and timestamp to ensure correctness
        decision.strategy = self.name
        decision.timestamp = datetime.now(timezone.utc)
        return decision

    def _build_system_prompt(self) -> str:
        if self.market == "tw":
            prompt = (
                f"你在交易台灣股票市場（TWSE）。所有分析和推理請用繁體中文。\n\n"
                f"You are an AI trading agent named '{self.display_name}' ({self.emoji}).\n"
                f"Strategy style: {self.style}\n\n"
                f"## Your Trading Rules\n{self.rules}\n\n"
                "## Important Instructions\n"
                "- You manage a simulated portfolio with real market data.\n"
                "- Starting capital is NT$300,000 (TWD).\n"
                "- You can only BUY or SELL Taiwan-listed stocks (tickers end with .TW).\n"
                "- You CANNOT short sell. You can only sell shares you own.\n"
                "- Each BUY order costs shares * current_price. You must have enough cash.\n"
                "- If there are no good trades right now, return an EMPTY orders list with reasoning.\n"
                "- Be specific about ticker symbols (e.g., 2330.TW, 2317.TW, 2454.TW).\n"
                "- Think step by step about your analysis before making decisions.\n"
                "- IMPORTANT: Write your market_analysis and reasoning in 繁體中文 (Traditional Chinese), "
                "keep it SHORT (2-3 sentences max). Keep ticker symbols and numbers in English.\n"
                "\n## 量化信號\n"
                "你會收到量化信號報告（由數學引擎計算）。每支股票有 -10 到 +10 的評分。\n"
                "- 分數 >= 5: 強烈買入信號。優先考慮。\n"
                "- 分數 2-4: 買入信號。可以考慮。\n"
                "- 分數 -1 到 1: 中性。除非有強烈信念否則不買。\n"
                "- 分數 <= -2: 賣出信號。避免買入，考慮賣出。\n"
                "- 報告包含基於 ATR 的建議止損價。數學 > 感覺。\n"
                "- 風險管理系統會自動驗證你的訂單。\n"
            )
        else:
            prompt = (
                f"You are an AI trading agent named '{self.display_name}' ({self.emoji}).\n"
                f"Strategy style: {self.style}\n\n"
                f"## Your Trading Rules\n{self.rules}\n\n"
                "## Important Instructions\n"
                "- You manage a simulated portfolio with real market data.\n"
                "- Starting capital is $10,000.\n"
                "- You can only BUY or SELL US-listed stocks.\n"
                "- You CANNOT short sell. You can only sell shares you own.\n"
                "- Each BUY order costs shares * current_price. You must have enough cash.\n"
                "- If there are no good trades right now, return an EMPTY orders list with reasoning.\n"
                "- Be specific about ticker symbols (e.g., AAPL, MSFT, NVDA).\n"
                "- Think step by step about your analysis before making decisions.\n"
                "- IMPORTANT: Write your market_analysis and reasoning in 繁體中文 (Traditional Chinese), "
                "keep it SHORT (2-3 sentences max). Keep ticker symbols and numbers in English.\n"
                "\n## Quantitative Signals\n"
                "You will receive a QUANTITATIVE SIGNAL REPORT computed by our math engine.\n"
                "Each stock has a score from -10 to +10 based on RSI, MACD, SMA, Bollinger Bands, and volume.\n"
                "- Score >= 5: STRONG BUY signal. Prioritize these.\n"
                "- Score 2-4: BUY signal. Consider these.\n"
                "- Score -1 to 1: NEUTRAL. Look for other reasons to buy (value, earnings, news).\n"
                "- Score <= -2: SELL signal if held. But oversold stocks (RSI < 30) can be buying opportunities!\n"
                "- The report also includes suggested stop-loss prices based on ATR.\n"
                "- IMPORTANT: You are here to TRADE, not just hold cash. If you see ANY reasonable opportunity, take it.\n"
                "- Even in uncertain markets, deploy at least 40-60% of your capital. Sitting in 100% cash means you're not doing your job.\n"
                "- Look for contrarian opportunities: when everyone is selling, value investors should be buying.\n"
                "- A risk management system will validate your orders. Oversized orders will be reduced automatically.\n"
            )
        if self.watchlist is not None:
            tickers_str = ", ".join(self.watchlist)
            prompt += (
                f"\nIMPORTANT: You may ONLY buy stocks from this watchlist: {tickers_str}. "
                "Any BUY order for a stock NOT on this list will be rejected.\n"
            )
        return prompt

    def _build_user_prompt(
        self,
        state: PortfolioState,
        market_data: str,
        news: str,
    ) -> str:
        currency_symbol = "NT$" if self.market == "tw" else "$"
        positions_str = "None" if not state.positions else "\n".join(
            f"  - {t}: {p.shares} shares @ avg {currency_symbol}{p.avg_cost:.2f} (current {currency_symbol}{p.current_price:.2f})"
            for t, p in state.positions.items()
        )

        return (
            "## Current Portfolio\n"
            f"Cash: {currency_symbol}{state.cash:,.2f}\n"
            f"Total Value: {currency_symbol}{state.total_value:,.2f}\n"
            f"Return: {state.total_return_pct:+.2f}%\n"
            f"Trade Count: {state.trade_count}\n"
            f"Positions:\n{positions_str}\n\n"
            f"## Market Data\n{market_data}\n\n"
            f"## News\n{news or 'No recent news available.'}\n\n"
            "## Your Task\n"
            "Analyze the market conditions and your portfolio, then decide on trades.\n"
            "Return your decision as a TradeDecision JSON with these fields:\n"
            "- strategy: your strategy name\n"
            "- timestamp: current ISO timestamp\n"
            "- market_analysis: brief analysis of current market conditions\n"
            "- orders: list of TradeOrder objects (action, ticker, shares, reason) — can be empty\n"
            "- reasoning: explain your overall reasoning for this cycle's decisions\n"
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
        "- Patience is your edge — but even Buffett says 'be greedy when others are fearful.'\n"
        "- In down markets, look for quality companies at discount prices. Deploy at least 50% of capital.\n"
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
        "- Always be at least 60% invested. Cash doesn't disrupt anything.\n"
    )


class MomentumStrategy(TradingStrategy):
    name = "aggressive"
    display_name = "Momentum Bot"
    emoji = "\u26a1"  # lightning
    description = "Pure momentum and growth: chase breakouts, cut losses fast, let winners run."
    model = "gpt-5.4"
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
        "- If the market is flat, look for sector rotation opportunities. Something is always moving.\n"
        "- Never sit in more than 40% cash. Deploy capital aggressively.\n"
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
        "- A balanced portfolio should always be at least 50% invested. Pure cash is not balanced.\n"
    )


class QuantStrategy(TradingStrategy):
    name = "quant"
    display_name = "Quant Engine"
    emoji = "\U0001f916"  # robot
    description = "Data-driven signals only: RSI, MACD, moving averages, volume. No narrative."
    model = "gpt-5.4"
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
        "- If signals are mixed or weak, be selective but still trade. RSI < 30 is always a mean-reversion BUY signal.\n"
        "- Deploy at least 50% of capital when multiple oversold signals exist simultaneously.\n"
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
