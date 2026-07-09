"""Tests for the soul-agent machinery: intents, seasons, journal, agent state,
trigger logic, and the extended TradeDecision model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.db.sqlite import Database
from api.trading.models import ConditionalOrder, TradeDecision, WakeTrigger
from api.trading.scheduler import _trigger_hit


@pytest.fixture
def db(tmp_path):
    d = Database(db_path=str(tmp_path / "soul.db"))
    d.init_db()
    return d


# --- Trigger logic ---

def test_trigger_price_below():
    assert _trigger_hit("price_below", 100.0, 99.9) is True
    assert _trigger_hit("price_below", 100.0, 100.0) is False


def test_trigger_price_at_or_above():
    assert _trigger_hit("price_at_or_above", 100.0, 100.0) is True
    assert _trigger_hit("price_at_or_above", 100.0, 99.9) is False


def test_trigger_unknown_type_never_fires():
    assert _trigger_hit("nonsense", 100.0, 50.0) is False


# --- TradeDecision soul fields ---

def test_decision_soul_fields_default_empty():
    d = TradeDecision(
        strategy="quant", timestamp=datetime.now(timezone.utc),
        market_analysis="x", orders=[], reasoning="y",
    )
    assert d.conditional_orders == []
    assert d.wake_triggers == []
    assert d.next_check_hours == 24.0
    assert d.journal == ""


def test_conditional_order_validation():
    co = ConditionalOrder(
        action="BUY", ticker="NVDA", shares=10,
        trigger="price_below", trigger_price=150.0, reason="dip buy",
    )
    assert co.good_for_days == 5
    with pytest.raises(Exception):
        ConditionalOrder(
            action="BUY", ticker="NVDA", shares=10,
            trigger="price_below", trigger_price=-5.0, reason="bad",
        )


def test_next_check_hours_bounds():
    with pytest.raises(Exception):
        TradeDecision(
            strategy="q", timestamp=datetime.now(timezone.utc),
            market_analysis="x", orders=[], reasoning="y",
            next_check_hours=500.0,  # > 120 cap
        )


# --- Intents lifecycle ---

def _intent(ticker="NVDA", kind="conditional_order", days=5, **kw):
    base = {
        "kind": kind, "action": "BUY", "ticker": ticker, "shares": 10,
        "trigger_type": "price_below", "trigger_price": 150.0, "reason": "test",
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
    }
    base.update(kw)
    return base


def test_replace_intents_cancels_previous(db):
    db.replace_intents("quant", [_intent("NVDA")])
    db.replace_intents("quant", [_intent("AAPL")])
    active = db.get_active_intents("quant")
    assert len(active) == 1
    assert active[0]["ticker"] == "AAPL"


def test_intents_isolated_per_strategy(db):
    db.replace_intents("quant", [_intent("NVDA")])
    db.replace_intents("ark", [_intent("TSLA")])
    assert len(db.get_active_intents("quant")) == 1
    assert len(db.get_active_intents()) == 2


def test_expire_stale_intents(db):
    db.replace_intents("quant", [_intent("NVDA", days=-1)])  # already expired
    assert db.expire_stale_intents() == 1
    assert db.get_active_intents("quant") == []


def test_intent_status_transition(db):
    db.replace_intents("quant", [_intent("NVDA")])
    intent_id = db.get_active_intents("quant")[0]["id"]
    db.set_intent_status(intent_id, "filled", filled_trade_id=42)
    assert db.get_active_intents("quant") == []


# --- Journal ---

def test_journal_roundtrip(db):
    db.save_journal_entry("quant", "今天 NVDA 訊號轉強，先佈局一半。", wake_reason="scheduled")
    db.save_journal_entry("quant", "續抱，等財報。")
    entries = db.get_recent_journal("quant", limit=5)
    assert len(entries) == 2
    assert entries[0]["entry"].startswith("今天")  # chronological order
    assert entries[1]["entry"] == "續抱，等財報。"


def test_empty_journal_not_saved(db):
    db.save_journal_entry("quant", "   ")
    assert db.get_recent_journal("quant") == []


# --- Agent state ---

def test_agent_state_roundtrip(db):
    now = datetime.now(timezone.utc).isoformat()
    db.save_agent_state("quant", next_wakeup=now, watchlist=["NVDA", "AAPL"])
    st = db.get_agent_state("quant")
    assert st["watchlist"] == ["NVDA", "AAPL"]
    assert st["next_wakeup"] == now


# --- Seasons ---

def test_new_season_archives_portfolios_and_resets(db):
    db.save_portfolio_state("quant", '{"strategy": "quant", "cash": 5000}')
    db.replace_intents("quant", [_intent("NVDA")])
    db.save_journal_entry("quant", "season 1 memories")

    assert db.get_current_season() == 1
    new = db.start_new_season()
    assert new == 2
    assert db.get_current_season() == 2

    # Portfolio archived under a season-suffixed key; fresh lookup finds nothing
    assert db.load_portfolio_state("quant") is None
    assert db.load_portfolio_state("quant@s1") is not None
    # Intents cancelled, agent state cleared
    assert db.get_active_intents() == []
    # Season-2 journal reads exclude season-1 entries
    assert db.get_recent_journal("quant") == []


def test_season_scoping_of_trades_and_snapshots(db):
    from api.trading.models import TradeRecord

    db.save_trade(TradeRecord(
        timestamp=datetime.now(timezone.utc), strategy="quant", action="BUY",
        ticker="NVDA", shares=1, price=100.0, total_cost=100.0, fees=0.0,
        reason="s1", portfolio_value_after=10_000.0,
    ))
    db.save_snapshot("quant", datetime.now(timezone.utc), 10_000.0)
    db.start_new_season()
    assert db.get_trades(strategy="quant") == []
    assert db.get_snapshots("quant") == []
    db.save_snapshot("quant", datetime.now(timezone.utc), 9_999.0)
    assert len(db.get_snapshots("quant")) == 1
