"""Tests for all Pydantic models: validation and serialization."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from api.trading.models import (
    PortfolioState,
    Position,
    StrategyInfo,
    TradeDecision,
    TradeOrder,
    TradeRecord,
)


class TestTradeOrder:
    def test_valid_buy(self):
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="test")
        assert order.action == "BUY"
        assert order.ticker == "AAPL"
        assert order.shares == 10

    def test_valid_sell(self):
        order = TradeOrder(action="SELL", ticker="TSLA", shares=5, reason="take profit")
        assert order.action == "SELL"

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            TradeOrder(action="HOLD", ticker="AAPL", shares=10, reason="invalid")

    def test_zero_shares_rejected(self):
        with pytest.raises(ValidationError):
            TradeOrder(action="BUY", ticker="AAPL", shares=0, reason="zero shares")

    def test_negative_shares_rejected(self):
        with pytest.raises(ValidationError):
            TradeOrder(action="BUY", ticker="AAPL", shares=-5, reason="negative")

    def test_serialization(self):
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="test")
        data = order.model_dump()
        assert data == {
            "action": "BUY",
            "ticker": "AAPL",
            "shares": 10,
            "reason": "test",
        }
        restored = TradeOrder.model_validate(data)
        assert restored == order


class TestTradeDecision:
    def test_valid_with_orders(self):
        decision = TradeDecision(
            strategy="buffett",
            timestamp=datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc),
            market_analysis="Market is fairly valued",
            orders=[
                TradeOrder(action="BUY", ticker="AAPL", shares=5, reason="undervalued"),
            ],
            reasoning="Strong fundamentals at current price",
        )
        assert len(decision.orders) == 1
        assert decision.strategy == "buffett"

    def test_valid_empty_orders(self):
        decision = TradeDecision(
            strategy="quant",
            timestamp=datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc),
            market_analysis="No clear signals",
            orders=[],
            reasoning="All indicators are neutral, staying on sidelines",
        )
        assert decision.orders == []

    def test_serialization_roundtrip(self):
        decision = TradeDecision(
            strategy="ark",
            timestamp=datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc),
            market_analysis="AI sector heating up",
            orders=[
                TradeOrder(action="BUY", ticker="NVDA", shares=3, reason="AI moat"),
            ],
            reasoning="Conviction play on AI convergence",
        )
        data = decision.model_dump(mode="json")
        restored = TradeDecision.model_validate(data)
        assert restored.strategy == decision.strategy
        assert len(restored.orders) == 1


class TestPosition:
    def test_basic(self):
        pos = Position(ticker="AAPL", shares=10, avg_cost=150.0, current_price=160.0)
        assert pos.ticker == "AAPL"
        assert pos.shares == 10

    def test_default_current_price(self):
        pos = Position(ticker="MSFT", shares=5, avg_cost=300.0)
        assert pos.current_price == 0.0

    def test_serialization(self):
        pos = Position(ticker="AAPL", shares=10, avg_cost=150.0, current_price=160.0)
        data = pos.model_dump()
        restored = Position.model_validate(data)
        assert restored == pos


class TestPortfolioState:
    def test_basic(self):
        state = PortfolioState(
            strategy="buffett",
            cash=8500.0,
            positions={
                "AAPL": Position(ticker="AAPL", shares=10, avg_cost=150.0, current_price=160.0),
            },
            total_value=10100.0,
            total_return_pct=1.0,
            trade_count=1,
        )
        assert state.strategy == "buffett"
        assert len(state.positions) == 1

    def test_empty_positions(self):
        state = PortfolioState(
            strategy="quant",
            cash=10000.0,
            positions={},
            total_value=10000.0,
            total_return_pct=0.0,
            trade_count=0,
        )
        assert state.positions == {}

    def test_serialization(self):
        state = PortfolioState(
            strategy="balanced",
            cash=5000.0,
            positions={
                "MSFT": Position(ticker="MSFT", shares=5, avg_cost=300.0, current_price=320.0),
            },
            total_value=6600.0,
            total_return_pct=-34.0,
            trade_count=3,
        )
        data = state.model_dump(mode="json")
        restored = PortfolioState.model_validate(data)
        assert restored.strategy == state.strategy
        assert "MSFT" in restored.positions


class TestTradeRecord:
    def test_basic(self):
        record = TradeRecord(
            id=1,
            timestamp=datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc),
            strategy="buffett",
            action="BUY",
            ticker="AAPL",
            shares=10,
            price=150.0,
            total_cost=1500.0,
            reason="Strong value",
            portfolio_value_after=10000.0,
        )
        assert record.id == 1

    def test_optional_id(self):
        record = TradeRecord(
            timestamp=datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc),
            strategy="ark",
            action="SELL",
            ticker="TSLA",
            shares=5,
            price=200.0,
            total_cost=1000.0,
            reason="thesis changed",
            portfolio_value_after=9500.0,
        )
        assert record.id is None

    def test_serialization(self):
        record = TradeRecord(
            id=42,
            timestamp=datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc),
            strategy="aggressive",
            action="BUY",
            ticker="NVDA",
            shares=3,
            price=800.0,
            total_cost=2400.0,
            reason="momentum breakout",
            portfolio_value_after=10200.0,
        )
        data = record.model_dump(mode="json")
        restored = TradeRecord.model_validate(data)
        assert restored.id == 42
        assert restored.ticker == "NVDA"


class TestStrategyInfo:
    def test_basic(self):
        info = StrategyInfo(
            name="buffett",
            display_name="Warren AI",
            emoji="\U0001f9d3",
            description="Value investing",
            model="claude-opus",
            style="buffett",
        )
        assert info.name == "buffett"
        assert info.model == "claude-opus"

    def test_serialization(self):
        info = StrategyInfo(
            name="quant",
            display_name="Quant Engine",
            emoji="\U0001f916",
            description="Data-driven",
            model="gpt-5.4",
            style="quant",
        )
        data = info.model_dump()
        restored = StrategyInfo.model_validate(data)
        assert restored == info
