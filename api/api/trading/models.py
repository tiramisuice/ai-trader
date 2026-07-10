"""Pydantic models for the trading system."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TradeOrder(BaseModel):
    action: Literal["BUY", "SELL"]
    ticker: str
    shares: int = Field(ge=1)
    reason: str


class ConditionalOrder(BaseModel):
    """An order the agent pre-commits to, executed without waking it when the
    trigger price is hit. This is how agents express 'buy NVDA if it dips'."""

    action: Literal["BUY", "SELL"]
    ticker: str
    shares: int = Field(ge=1)
    trigger: Literal["price_below", "price_at_or_above"]
    trigger_price: float = Field(gt=0)
    good_for_days: int = Field(ge=1, le=30, default=5)
    reason: str


class WakeTrigger(BaseModel):
    """A condition that wakes the agent for a fresh decision (no pre-committed
    order) — 'wake me if TSLA breaks 300 and I'll decide then'."""

    ticker: str
    condition: Literal["price_below", "price_at_or_above"]
    price: float = Field(gt=0)


class TradeDecision(BaseModel):
    strategy: str
    timestamp: datetime
    market_analysis: str
    orders: list[TradeOrder]
    reasoning: str
    # ── Agent autonomy (soul) fields ────────────────────────────
    conditional_orders: list[ConditionalOrder] = Field(default_factory=list)
    wake_triggers: list[WakeTrigger] = Field(default_factory=list)
    # When the agent wants its next scheduled look at the market, in hours.
    # It can sleep for days if nothing interests it.
    next_check_hours: float = Field(ge=0.25, le=48, default=8.0)
    # The agent's trading diary — thesis, plans, feelings. Fed back next wake.
    journal: str = ""
    watchlist_add: list[str] = Field(default_factory=list)
    watchlist_remove: list[str] = Field(default_factory=list)


class Position(BaseModel):
    ticker: str
    shares: int
    avg_cost: float
    current_price: float = 0.0


class PortfolioState(BaseModel):
    strategy: str
    cash: float
    positions: dict[str, Position]
    total_value: float
    total_return_pct: float
    trade_count: int
    market: str = "us"
    currency: str = "USD"


class TradeRecord(BaseModel):
    id: int | None = None
    timestamp: datetime
    strategy: str
    action: str
    ticker: str
    shares: int
    price: float
    total_cost: float  # cash impact: gross + fees on BUY, net proceeds on SELL
    fees: float = 0.0  # commission + tax + slippage included in total_cost
    reason: str
    portfolio_value_after: float


class StrategyInfo(BaseModel):
    name: str
    display_name: str
    emoji: str
    description: str
    model: str
    style: str  # "buffett", "ark", "momentum", "balanced", "quant"
    watchlist: list[str] | None = None
    market: str = "us"
