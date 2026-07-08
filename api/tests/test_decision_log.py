"""Tests for the decision logging system (DB + API)."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from api.db.sqlite import Database


@pytest.fixture
def test_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    database = Database(db_path=path)
    database.init_db()
    yield database
    # Close the SQLite connection before cleanup (required on Windows)
    conn = database._get_conn()
    conn.close()
    database._local.conn = None
    try:
        os.unlink(path)
    except OSError:
        pass  # Windows may still hold the WAL file


def _make_log_kwargs(strategy: str = "buffett", cycle: int = 1, **overrides):
    """Helper to build save_decision_log kwargs with sensible defaults."""
    defaults = {
        "strategy": strategy,
        "cycle_number": cycle,
        "timestamp": "2026-04-02T12:00:00+00:00",
        "pipeline_json": json.dumps({"regime": None, "top_signals": [], "tickers_scanned": 5}),
        "llm_input_json": json.dumps({"market_data_preview": "test data", "news_preview": "test news"}),
        "llm_output_json": json.dumps({
            "market_analysis": "Market looks bullish",
            "reasoning": "Strong signals",
            "orders_proposed": [{"action": "BUY", "ticker": "AAPL", "shares": 10, "reason": "good price"}],
        }),
        "risk_check_json": json.dumps({
            "orders_approved": [{"action": "BUY", "ticker": "AAPL", "shares": 10, "original_shares": 15, "adjustments": ["Risk rules reduced from 15 to 10"]}],
            "orders_blocked": [],
        }),
        "execution_json": json.dumps({
            "trades_executed": [{"action": "BUY", "ticker": "AAPL", "shares": 10}],
            "portfolio_after": {"cash": 8500.0, "total_value": 10050.0, "return_pct": 0.5},
        }),
    }
    defaults.update(overrides)
    return defaults


def test_save_and_get_decision_log(test_db: Database):
    """Save a decision log and retrieve it."""
    kwargs = _make_log_kwargs()
    row_id = test_db.save_decision_log(**kwargs)
    assert row_id > 0

    result = test_db.get_latest_decision_log("buffett")
    assert result is not None
    assert result["id"] == row_id
    assert result["strategy"] == "buffett"
    assert result["cycle_number"] == 1
    assert result["timestamp"] == "2026-04-02T12:00:00+00:00"


def test_get_latest_returns_most_recent(test_db: Database):
    """get_latest_decision_log returns the most recently inserted row."""
    test_db.save_decision_log(**_make_log_kwargs(cycle=1, timestamp="2026-04-02T10:00:00+00:00"))
    test_db.save_decision_log(**_make_log_kwargs(cycle=2, timestamp="2026-04-02T11:00:00+00:00"))
    id3 = test_db.save_decision_log(**_make_log_kwargs(cycle=3, timestamp="2026-04-02T12:00:00+00:00"))

    result = test_db.get_latest_decision_log("buffett")
    assert result is not None
    assert result["id"] == id3
    assert result["cycle_number"] == 3


def test_get_history_respects_limit(test_db: Database):
    """get_decision_log_history returns at most `limit` rows, newest first."""
    for i in range(5):
        test_db.save_decision_log(**_make_log_kwargs(cycle=i + 1))

    history = test_db.get_decision_log_history("buffett", limit=3)
    assert len(history) == 3
    # Newest first
    assert history[0]["cycle_number"] == 5
    assert history[1]["cycle_number"] == 4
    assert history[2]["cycle_number"] == 3

    # Default limit
    history_all = test_db.get_decision_log_history("buffett")
    assert len(history_all) == 5


def test_get_latest_nonexistent_strategy_returns_none(test_db: Database):
    """Querying a strategy with no logs returns None."""
    result = test_db.get_latest_decision_log("nonexistent_strategy")
    assert result is None

    history = test_db.get_decision_log_history("nonexistent_strategy")
    assert history == []


def test_json_fields_are_parsed(test_db: Database):
    """JSON string columns are parsed back into dicts/lists."""
    test_db.save_decision_log(**_make_log_kwargs())
    result = test_db.get_latest_decision_log("buffett")
    assert result is not None

    # pipeline is a dict
    assert isinstance(result["pipeline"], dict)
    assert result["pipeline"]["tickers_scanned"] == 5
    assert result["pipeline"]["regime"] is None
    assert result["pipeline"]["top_signals"] == []

    # llm_input is a dict
    assert isinstance(result["llm_input"], dict)
    assert result["llm_input"]["market_data_preview"] == "test data"

    # llm_output is a dict
    assert isinstance(result["llm_output"], dict)
    assert result["llm_output"]["market_analysis"] == "Market looks bullish"
    assert len(result["llm_output"]["orders_proposed"]) == 1
    assert result["llm_output"]["orders_proposed"][0]["ticker"] == "AAPL"

    # risk_check is a dict
    assert isinstance(result["risk_check"], dict)
    assert len(result["risk_check"]["orders_approved"]) == 1
    assert result["risk_check"]["orders_blocked"] == []

    # execution is a dict
    assert isinstance(result["execution"], dict)
    assert result["execution"]["portfolio_after"]["cash"] == 8500.0
    assert result["execution"]["portfolio_after"]["return_pct"] == 0.5
