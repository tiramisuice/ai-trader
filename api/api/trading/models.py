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


class TradeDecision(BaseModel):
    strategy: str
    timestamp: datetime
    market_analysis: str
    orders: list[TradeOrder]
    reasoning: str


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
    total_cost: float
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
