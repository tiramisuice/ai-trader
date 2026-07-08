"""Tests for the safety guards added in the bug-fix pass:
market-open calendar guard, daily-loss baseline lookup, price-map validation,
cache eviction, and cost-tracker memory cap."""

from __future__ import annotations

import pandas as pd
import pytest

from api.data import market
from api.db.sqlite import Database
from api.llm.client import CostTracker
from api.trading.market_hours import is_market_open


# --- Market-open guard ---

def test_us_market_open_regular_session():
    # Tuesday 2026-07-07 15:00 UTC = 11:00 ET — NYSE open
    assert is_market_open("us", pd.Timestamp("2026-07-07 15:00", tz="UTC")) is True


def test_us_market_closed_preopen():
    # 2026-07-07 13:15 UTC = 9:15 ET — before the 9:30 open (the old cron fired here)
    assert is_market_open("us", pd.Timestamp("2026-07-07 13:15", tz="UTC")) is False


def test_us_market_closed_holiday():
    # 2026-07-03 (Friday) — Independence Day observed, NYSE closed
    assert is_market_open("us", pd.Timestamp("2026-07-03 15:00", tz="UTC")) is False


def test_tw_market_open_regular_session():
    # Tuesday 2026-07-07 02:00 UTC = 10:00 Asia/Taipei — TWSE open
    assert is_market_open("tw", pd.Timestamp("2026-07-07 02:00", tz="UTC")) is True


def test_tw_market_closed_after_1330():
    # 2026-07-07 05:45 UTC = 13:45 Asia/Taipei — after the 13:30 close
    # (the old cron fired a cycle here every day)
    assert is_market_open("tw", pd.Timestamp("2026-07-07 05:45", tz="UTC")) is False


def test_weekend_closed_both_markets():
    saturday = pd.Timestamp("2026-07-04 15:00", tz="UTC")
    assert is_market_open("us", saturday) is False
    assert is_market_open("tw", saturday) is False


# --- Daily-loss baseline lookup ---

def test_get_first_snapshot_since(tmp_path):
    db = Database(db_path=str(tmp_path / "test.db"))
    db.init_db()
    from datetime import datetime, timezone

    db.save_snapshot("quant", datetime(2026, 7, 6, 15, 0, tzinfo=timezone.utc), 9000.0)
    db.save_snapshot("quant", datetime(2026, 7, 7, 13, 30, tzinfo=timezone.utc), 10000.0)
    db.save_snapshot("quant", datetime(2026, 7, 7, 14, 0, tzinfo=timezone.utc), 10100.0)

    # First snapshot of July 7 — not yesterday's, not the later one
    baseline = db.get_first_snapshot_since("quant", "2026-07-07T00:00:00+00:00")
    assert baseline == 10000.0

    # No snapshots yet in the window
    assert db.get_first_snapshot_since("quant", "2026-07-08T00:00:00+00:00") is None
    assert db.get_first_snapshot_since("unknown", "2026-07-07T00:00:00+00:00") is None


# --- Price-map validation ---

def test_get_portfolio_prices_omits_invalid(monkeypatch):
    def fake_price_data(ticker):
        return {"ticker": ticker, "current_price": 0.0 if ticker == "BAD" else 100.0}

    monkeypatch.setattr(market, "get_price_data", fake_price_data)
    market._cache.clear()

    prices = market.get_portfolio_prices(["AAPL", "BAD"])
    assert prices == {"AAPL": 100.0}  # BAD omitted, NOT stored as 0.0


# --- RSI helper ---

def test_rsi_flat_series_no_nan():
    flat = pd.Series([100.0] * 30)
    rsi = market._rsi_14(flat)
    assert rsi == 50.0  # 0/0 case must not be NaN


def test_rsi_insufficient_data():
    assert market._rsi_14(pd.Series([100.0, 101.0])) is None


# --- Cache eviction ---

def test_market_cache_bounded():
    market._cache.clear()
    for i in range(market._CACHE_MAX_ENTRIES + 50):
        market._set_cached(f"key:{i}", i)
    assert len(market._cache) <= market._CACHE_MAX_ENTRIES + 1


# --- CostTracker cap ---

def test_cost_tracker_caps_records_but_keeps_totals():
    tracker = CostTracker()
    for _ in range(CostTracker.MAX_RECORDS + 500):
        tracker.record("test-model", 100, 50, 0.01)

    assert len(tracker.records) == CostTracker.MAX_RECORDS
    assert tracker.total_tokens == (CostTracker.MAX_RECORDS + 500) * 150
    assert tracker.total_cost == pytest.approx((CostTracker.MAX_RECORDS + 500) * 0.01)
