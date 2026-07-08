"""Tests for the transaction cost model and its portfolio integration."""

from __future__ import annotations

import pytest

from api.trading.costs import (
    TW_COST_MODEL,
    US_COST_MODEL,
    ZERO_COST_MODEL,
    cost_model_for_currency,
)
from api.trading.models import TradeOrder
from api.trading.portfolio import SimulatedPortfolio


# --- CostModel math ---

def test_tw_buy_costs():
    # 1000 shares @ NT$100 = NT$100,000 gross
    c = TW_COST_MODEL.for_trade("BUY", 1000, 100.0)
    assert c.commission == pytest.approx(142.5)   # 0.1425%
    assert c.tax == 0.0                            # no tax on buys
    assert c.slippage == pytest.approx(50.0)       # 5 bps
    assert c.total == pytest.approx(192.5)


def test_tw_sell_costs_include_transaction_tax():
    c = TW_COST_MODEL.for_trade("SELL", 1000, 100.0)
    assert c.commission == pytest.approx(142.5)
    assert c.tax == pytest.approx(300.0)           # 0.3% securities tax
    assert c.total == pytest.approx(492.5)


def test_tw_minimum_commission():
    # Tiny trade: NT$1,000 gross → 0.1425% = NT$1.43, floored to NT$20
    c = TW_COST_MODEL.for_trade("BUY", 10, 100.0)
    assert c.commission == 20.0


def test_us_costs_commission_free_with_slippage():
    c = US_COST_MODEL.for_trade("BUY", 10, 100.0)
    assert c.commission == 0.0
    assert c.tax == 0.0
    assert c.slippage == pytest.approx(0.5)        # 5 bps of $1,000


def test_zero_model_is_free():
    c = ZERO_COST_MODEL.for_trade("SELL", 1000, 500.0)
    assert c.total == 0.0


def test_model_selected_by_currency():
    assert cost_model_for_currency("TWD") is TW_COST_MODEL
    assert cost_model_for_currency("USD") is US_COST_MODEL


# --- Portfolio integration ---

def test_buy_deducts_fees_from_cash():
    p = SimulatedPortfolio("t", cash=10_000.0, currency="USD")
    record = p.execute_order(TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="x"), 100.0)
    assert record is not None
    assert record.fees == pytest.approx(0.5)               # 5 bps slippage
    assert record.total_cost == pytest.approx(1000.5)
    assert p.cash == pytest.approx(10_000.0 - 1000.5)
    # Fees are capitalized into cost basis
    assert p.positions["AAPL"].avg_cost == pytest.approx(100.05)


def test_sell_nets_fees_from_proceeds():
    p = SimulatedPortfolio("t", cash=300_000.0, currency="TWD")
    p.execute_order(TradeOrder(action="BUY", ticker="2330.TW", shares=100, reason="x"), 1000.0)
    record = p.execute_order(TradeOrder(action="SELL", ticker="2330.TW", shares=100, reason="x"), 1000.0)
    assert record is not None
    # Sell NT$100,000: 142.5 commission + 300 tax + 50 slippage = 492.5
    assert record.fees == pytest.approx(492.5)
    assert record.total_cost == pytest.approx(100_000.0 - 492.5)


def test_round_trip_at_same_price_loses_money_tw():
    """A TW round trip at an unchanged price must lose ~0.64% — the whole
    point of modeling costs (this used to be free)."""
    p = SimulatedPortfolio("t", cash=300_000.0, currency="TWD")
    p.execute_order(TradeOrder(action="BUY", ticker="2330.TW", shares=100, reason="x"), 1000.0)
    p.execute_order(TradeOrder(action="SELL", ticker="2330.TW", shares=100, reason="x"), 1000.0)
    assert p.cash < 300_000.0
    assert p.cash == pytest.approx(300_000.0 - 192.5 - 492.5)


def test_buy_rejected_when_fees_push_over_cash():
    p = SimulatedPortfolio("t", cash=1000.0, currency="USD")
    # Gross exactly equals cash, but slippage pushes it over
    record = p.execute_order(TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="x"), 100.0)
    assert record is None
    assert p.cash == 1000.0


def test_zero_cost_model_preserves_old_behavior():
    p = SimulatedPortfolio("t", cash=10_000.0, currency="USD", cost_model=ZERO_COST_MODEL)
    record = p.execute_order(TradeOrder(action="BUY", ticker="AAPL", shares=10, reason="x"), 100.0)
    assert record.fees == 0.0
    assert record.total_cost == pytest.approx(1000.0)
    assert p.positions["AAPL"].avg_cost == pytest.approx(100.0)


def test_from_dict_selects_cost_model_by_currency():
    p = SimulatedPortfolio.from_dict({"strategy": "tw_quant", "cash": 300_000.0, "currency": "TWD"})
    assert p.cost_model is TW_COST_MODEL
