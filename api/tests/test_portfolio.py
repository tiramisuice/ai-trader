"""Tests for SimulatedPortfolio: buy, sell, edge cases, serialization."""

from __future__ import annotations

import pytest

from api.trading.models import TradeOrder
from api.trading.portfolio import STARTING_CAPITAL, SimulatedPortfolio


class TestBuy:
    def test_buy_basic(self):
        p = SimulatedPortfolio(strategy="test")
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="test buy")
        record = p.execute_order(order, price=150.0)

        assert record is not None
        assert record.action == "BUY"
        assert record.ticker == "AAPL"
        assert record.shares == 10
        assert record.price == 150.0
        assert record.total_cost == 1500.0
        assert p.cash == STARTING_CAPITAL - 1500.0
        assert "AAPL" in p.positions
        assert p.positions["AAPL"].shares == 10
        assert p.positions["AAPL"].avg_cost == 150.0
        assert p.trade_count == 1

    def test_buy_insufficient_funds(self):
        p = SimulatedPortfolio(strategy="test", cash=100.0)
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="too expensive")
        record = p.execute_order(order, price=150.0)

        assert record is None
        assert p.cash == 100.0
        assert "AAPL" not in p.positions
        assert p.trade_count == 0

    def test_buy_exact_funds(self):
        p = SimulatedPortfolio(strategy="test", cash=1500.0)
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="all in")
        record = p.execute_order(order, price=150.0)

        assert record is not None
        assert p.cash == 0.0

    def test_buy_avg_cost_update(self):
        p = SimulatedPortfolio(strategy="test")
        # Buy 10 at $100
        order1 = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="first")
        p.execute_order(order1, price=100.0)
        # Buy 10 more at $200
        order2 = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="second")
        p.execute_order(order2, price=200.0)

        pos = p.positions["AAPL"]
        assert pos.shares == 20
        assert pos.avg_cost == 150.0  # (100*10 + 200*10) / 20

    def test_buy_zero_price_rejected(self):
        p = SimulatedPortfolio(strategy="test")
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="free?")
        record = p.execute_order(order, price=0.0)
        assert record is None

    def test_buy_negative_price_rejected(self):
        p = SimulatedPortfolio(strategy="test")
        order = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="negative")
        record = p.execute_order(order, price=-10.0)
        assert record is None


class TestSell:
    def test_sell_basic(self):
        p = SimulatedPortfolio(strategy="test")
        # Buy first
        buy = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="buy")
        p.execute_order(buy, price=150.0)

        # Sell
        sell = TradeOrder(action="SELL", ticker="AAPL", shares=5, reason="take profit")
        record = p.execute_order(sell, price=200.0)

        assert record is not None
        assert record.action == "SELL"
        assert record.total_cost == 1000.0  # 5 * 200
        assert p.cash == STARTING_CAPITAL - 1500.0 + 1000.0
        assert p.positions["AAPL"].shares == 5
        assert p.trade_count == 2

    def test_sell_all_shares_removes_position(self):
        p = SimulatedPortfolio(strategy="test")
        buy = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="buy")
        p.execute_order(buy, price=100.0)

        sell = TradeOrder(action="SELL", ticker="AAPL", shares=10, reason="sell all")
        p.execute_order(sell, price=120.0)

        assert "AAPL" not in p.positions
        assert p.cash == STARTING_CAPITAL - 1000.0 + 1200.0

    def test_sell_more_than_owned_rejected(self):
        p = SimulatedPortfolio(strategy="test")
        buy = TradeOrder(action="BUY", ticker="AAPL", shares=5, reason="buy")
        p.execute_order(buy, price=100.0)

        sell = TradeOrder(action="SELL", ticker="AAPL", shares=10, reason="too many")
        record = p.execute_order(sell, price=120.0)

        assert record is None
        assert p.positions["AAPL"].shares == 5

    def test_sell_nonexistent_position_rejected(self):
        p = SimulatedPortfolio(strategy="test")
        sell = TradeOrder(action="SELL", ticker="TSLA", shares=5, reason="no position")
        record = p.execute_order(sell, price=300.0)
        assert record is None


class TestPortfolioValue:
    def test_total_value_cash_only(self):
        p = SimulatedPortfolio(strategy="test")
        state = p.get_state()
        assert state.total_value == STARTING_CAPITAL
        assert state.total_return_pct == 0.0

    def test_total_value_with_positions(self):
        p = SimulatedPortfolio(strategy="test")
        buy = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="buy")
        p.execute_order(buy, price=100.0)

        # Update price
        p.update_prices({"AAPL": 120.0})
        state = p.get_state()

        # Cash: 10000 - 1000 = 9000
        # Position: 10 * 120 = 1200
        # Total: 10200
        assert state.total_value == 10200.0
        assert state.total_return_pct == 2.0

    def test_update_prices(self):
        p = SimulatedPortfolio(strategy="test")
        buy = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="buy")
        p.execute_order(buy, price=100.0)

        p.update_prices({"AAPL": 150.0, "MSFT": 300.0})
        assert p.positions["AAPL"].current_price == 150.0


class TestSerialization:
    def test_roundtrip(self):
        p = SimulatedPortfolio(strategy="test")
        buy = TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="buy")
        p.execute_order(buy, price=150.0)
        p.update_prices({"AAPL": 160.0})

        data = p.to_dict()
        restored = SimulatedPortfolio.from_dict(data)

        assert restored.strategy == "test"
        assert restored.cash == p.cash
        assert restored.trade_count == 1
        assert "AAPL" in restored.positions
        assert restored.positions["AAPL"].shares == 10
        assert restored.positions["AAPL"].avg_cost == 150.0

    def test_empty_portfolio_roundtrip(self):
        p = SimulatedPortfolio(strategy="empty")
        data = p.to_dict()
        restored = SimulatedPortfolio.from_dict(data)

        assert restored.strategy == "empty"
        assert restored.cash == STARTING_CAPITAL
        assert restored.positions == {}
        assert restored.trade_count == 0

    def test_get_state_model(self):
        p = SimulatedPortfolio(strategy="test")
        state = p.get_state()

        assert state.strategy == "test"
        assert state.cash == STARTING_CAPITAL
        assert state.positions == {}
        assert state.total_value == STARTING_CAPITAL
        assert state.total_return_pct == 0.0
        assert state.trade_count == 0
