"""SQLite database manager for persisting trades, portfolio states, and snapshots."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from api.trading.models import TradeRecord

logger = logging.getLogger(__name__)

# Use /data on Fly.io (persistent volume), fallback to local data/ dir
_DATA_DIR = "/data" if os.path.isdir("/data") else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "trading.db")


class Database:
    """Thread-safe SQLite database wrapper."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._local = threading.local()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            # US and TW cycles write concurrently; wait instead of raising
            # "database is locked" and losing the rest of the cycle's writes.
            self._local.conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                action TEXT NOT NULL,
                ticker TEXT NOT NULL,
                shares INTEGER NOT NULL,
                price REAL NOT NULL,
                total_cost REAL NOT NULL,
                reason TEXT NOT NULL,
                portfolio_value_after REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS portfolio_states (
                strategy TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                total_value REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy);
            CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
            CREATE INDEX IF NOT EXISTS idx_snapshots_strategy ON snapshots(strategy);
            CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp);

            CREATE TABLE IF NOT EXISTS decision_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy TEXT NOT NULL,
                cycle_number INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                pipeline_json TEXT NOT NULL,
                llm_input_json TEXT NOT NULL,
                llm_output_json TEXT NOT NULL,
                risk_check_json TEXT NOT NULL,
                execution_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_decision_strategy ON decision_log(strategy);
        """)
        conn.commit()
        logger.info("Database initialized at %s", self.db_path)

    def save_trade(self, record: TradeRecord) -> int:
        """Save a trade record and return its ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO trades (timestamp, strategy, action, ticker, shares, price, total_cost, reason, portfolio_value_after)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.timestamp.isoformat(),
                record.strategy,
                record.action,
                record.ticker,
                record.shares,
                record.price,
                record.total_cost,
                record.reason,
                record.portfolio_value_after,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def save_portfolio_state(self, strategy: str, state_json: str) -> None:
        """Upsert the portfolio state for a strategy."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO portfolio_states (strategy, state_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(strategy) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (strategy, state_json, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    def load_portfolio_state(self, strategy: str) -> dict[str, Any] | None:
        """Load portfolio state for a strategy. Returns None if not found."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT state_json FROM portfolio_states WHERE strategy = ?",
            (strategy,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["state_json"])

    def get_trades(self, strategy: str | None = None, limit: int = 50) -> list[TradeRecord]:
        """Get recent trades, optionally filtered by strategy."""
        conn = self._get_conn()
        if strategy:
            rows = conn.execute(
                "SELECT * FROM trades WHERE strategy = ? ORDER BY id DESC LIMIT ?",
                (strategy, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [
            TradeRecord(
                id=row["id"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                strategy=row["strategy"],
                action=row["action"],
                ticker=row["ticker"],
                shares=row["shares"],
                price=row["price"],
                total_cost=row["total_cost"],
                reason=row["reason"],
                portfolio_value_after=row["portfolio_value_after"],
            )
            for row in rows
        ]

    def get_snapshots(self, strategy: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get value snapshots for a strategy (for charting)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE strategy = ? ORDER BY id DESC LIMIT ?",
            (strategy, limit),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "strategy": row["strategy"],
                "timestamp": row["timestamp"],
                "total_value": row["total_value"],
            }
            for row in reversed(rows)  # Return chronological order
        ]

    def get_first_snapshot_since(self, strategy: str, since_iso: str) -> float | None:
        """Get the earliest snapshot value at/after `since_iso` (UTC ISO string).

        Used as the start-of-day baseline for the daily-loss circuit breaker.
        Returns None if no snapshot exists yet in that window.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT total_value FROM snapshots WHERE strategy = ? AND timestamp >= ? "
            "ORDER BY timestamp ASC LIMIT 1",
            (strategy, since_iso),
        ).fetchone()
        return row["total_value"] if row is not None else None

    def save_snapshot(self, strategy: str, timestamp: datetime, total_value: float) -> None:
        """Save a portfolio value snapshot."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO snapshots (strategy, timestamp, total_value) VALUES (?, ?, ?)",
            (strategy, timestamp.isoformat(), total_value),
        )
        conn.commit()

    def save_decision_log(
        self,
        strategy: str,
        cycle_number: int,
        timestamp: str,
        pipeline_json: str,
        llm_input_json: str,
        llm_output_json: str,
        risk_check_json: str,
        execution_json: str,
    ) -> int:
        """Save a decision log entry and return its ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO decision_log
               (strategy, cycle_number, timestamp, pipeline_json, llm_input_json, llm_output_json, risk_check_json, execution_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (strategy, cycle_number, timestamp, pipeline_json, llm_input_json, llm_output_json, risk_check_json, execution_json),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_latest_decision_log(self, strategy: str) -> dict[str, Any] | None:
        """Get the most recent decision log for a strategy, parsing JSON fields back to dicts."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM decision_log WHERE strategy = ? ORDER BY id DESC LIMIT 1",
            (strategy,),
        ).fetchone()
        if row is None:
            return None
        return self._decision_row_to_dict(row)

    def get_decision_log_history(self, strategy: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get decision log history for a strategy, most recent first."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM decision_log WHERE strategy = ? ORDER BY id DESC LIMIT ?",
            (strategy, limit),
        ).fetchall()
        return [self._decision_row_to_dict(row) for row in rows]

    @staticmethod
    def _decision_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a decision_log row to a dict, parsing JSON strings back to dicts."""
        return {
            "id": row["id"],
            "strategy": row["strategy"],
            "cycle_number": row["cycle_number"],
            "timestamp": row["timestamp"],
            "pipeline": json.loads(row["pipeline_json"]),
            "llm_input": json.loads(row["llm_input_json"]),
            "llm_output": json.loads(row["llm_output_json"]),
            "risk_check": json.loads(row["risk_check_json"]),
            "execution": json.loads(row["execution_json"]),
        }


# Singleton database instance
db = Database()
