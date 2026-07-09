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
        self._season_cache: int | None = None
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

            CREATE TABLE IF NOT EXISTS llm_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS intents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                kind TEXT NOT NULL,            -- 'conditional_order' | 'wake_trigger'
                action TEXT,                   -- BUY/SELL (conditional_order only)
                ticker TEXT NOT NULL,
                shares INTEGER,                -- conditional_order only
                trigger_type TEXT NOT NULL,    -- 'price_below' | 'price_at_or_above'
                trigger_price REAL NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',  -- active/filled/triggered/expired/cancelled
                filled_trade_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status, strategy);

            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season INTEGER NOT NULL,
                strategy TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                wake_reason TEXT NOT NULL DEFAULT '',
                entry TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_journal_strategy ON journal(strategy, id);

            CREATE TABLE IF NOT EXISTS agent_state (
                strategy TEXT PRIMARY KEY,
                next_wakeup TEXT NOT NULL,
                watchlist_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()

        # Migration: pre-existing trades tables lack the fees column
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(trades)")}
        if "fees" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN fees REAL NOT NULL DEFAULT 0")
            conn.commit()
            logger.info("Migrated trades table: added fees column")

        # Migration: season columns (season 1 = everything before the soul rework)
        for table in ("trades", "snapshots", "decision_log"):
            cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "season" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN season INTEGER NOT NULL DEFAULT 1")
                conn.commit()
                logger.info("Migrated %s table: added season column", table)

        logger.info("Database initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------

    def get_current_season(self) -> int:
        if getattr(self, "_season_cache", None) is not None:
            return self._season_cache
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM meta WHERE key = 'current_season'").fetchone()
        self._season_cache = int(row["value"]) if row else 1
        return self._season_cache

    def start_new_season(self) -> int:
        """Advance to a new season: archive portfolio states and agent state so
        every agent restarts with fresh capital. Historical rows keep their
        season number and remain queryable."""
        conn = self._get_conn()
        old = self.get_current_season()
        new = old + 1
        conn.execute(
            "UPDATE portfolio_states SET strategy = strategy || '@s' || ? "
            "WHERE strategy NOT LIKE '%@s%'",
            (old,),
        )
        conn.execute("DELETE FROM agent_state")
        conn.execute("UPDATE intents SET status = 'cancelled' WHERE status = 'active'")
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('current_season', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(new),),
        )
        conn.commit()
        self._season_cache = new
        logger.info("Season %d started (season %d archived)", new, old)
        return new

    # ------------------------------------------------------------------
    # Intents (conditional orders + wake triggers)
    # ------------------------------------------------------------------

    def replace_intents(self, strategy: str, intents: list[dict[str, Any]]) -> None:
        """Replace a strategy's active intents with a fresh set (each wake, the
        agent restates its standing orders — simplest consistent semantics)."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE intents SET status = 'cancelled' WHERE strategy = ? AND status = 'active'",
            (strategy,),
        )
        now = datetime.now(timezone.utc)
        for it in intents:
            conn.execute(
                """INSERT INTO intents (season, strategy, kind, action, ticker, shares,
                       trigger_type, trigger_price, reason, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.get_current_season(), strategy, it["kind"], it.get("action"),
                    it["ticker"], it.get("shares"), it["trigger_type"], it["trigger_price"],
                    it.get("reason", ""), now.isoformat(), it["expires_at"],
                ),
            )
        conn.commit()

    def get_active_intents(self, strategy: str | None = None) -> list[dict[str, Any]]:
        conn = self._get_conn()
        if strategy:
            rows = conn.execute(
                "SELECT * FROM intents WHERE status = 'active' AND strategy = ?", (strategy,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM intents WHERE status = 'active'").fetchall()
        return [dict(r) for r in rows]

    def set_intent_status(self, intent_id: int, status: str, filled_trade_id: int | None = None) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE intents SET status = ?, filled_trade_id = ? WHERE id = ?",
            (status, filled_trade_id, intent_id),
        )
        conn.commit()

    def expire_stale_intents(self) -> int:
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE intents SET status = 'expired' WHERE status = 'active' AND expires_at < ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------
    # Journal (the agent's diary)
    # ------------------------------------------------------------------

    def save_journal_entry(self, strategy: str, entry: str, wake_reason: str = "") -> None:
        if not entry.strip():
            return
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO journal (season, strategy, timestamp, wake_reason, entry) VALUES (?, ?, ?, ?, ?)",
            (self.get_current_season(), strategy, datetime.now(timezone.utc).isoformat(), wake_reason, entry),
        )
        conn.commit()

    def get_recent_journal(self, strategy: str, limit: int = 5) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT timestamp, wake_reason, entry FROM journal "
            "WHERE strategy = ? AND season = ? ORDER BY id DESC LIMIT ?",
            (strategy, self.get_current_season(), limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # Agent state (wakeup schedule + self-managed watchlist)
    # ------------------------------------------------------------------

    def get_agent_state(self, strategy: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM agent_state WHERE strategy = ?", (strategy,)).fetchone()
        if row is None:
            return None
        return {
            "strategy": row["strategy"],
            "next_wakeup": row["next_wakeup"],
            "watchlist": json.loads(row["watchlist_json"]),
        }

    def save_agent_state(self, strategy: str, next_wakeup: str, watchlist: list[str]) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO agent_state (strategy, next_wakeup, watchlist_json, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(strategy) DO UPDATE SET next_wakeup=excluded.next_wakeup,
                   watchlist_json=excluded.watchlist_json, updated_at=excluded.updated_at""",
            (strategy, next_wakeup, json.dumps(watchlist), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    def save_trade(self, record: TradeRecord) -> int:
        """Save a trade record and return its ID."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO trades (timestamp, strategy, action, ticker, shares, price, total_cost, fees, reason, portfolio_value_after, season)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.timestamp.isoformat(),
                record.strategy,
                record.action,
                record.ticker,
                record.shares,
                record.price,
                record.total_cost,
                record.fees,
                record.reason,
                record.portfolio_value_after,
                self.get_current_season(),
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
        season = self.get_current_season()
        if strategy:
            rows = conn.execute(
                "SELECT * FROM trades WHERE strategy = ? AND season = ? ORDER BY id DESC LIMIT ?",
                (strategy, season, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE season = ? ORDER BY id DESC LIMIT ?",
                (season, limit),
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
                fees=row["fees"] if "fees" in row.keys() else 0.0,
                reason=row["reason"],
                portfolio_value_after=row["portfolio_value_after"],
            )
            for row in rows
        ]

    def get_snapshots(self, strategy: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get value snapshots for a strategy (for charting). Current season only."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE strategy = ? AND season = ? ORDER BY id DESC LIMIT ?",
            (strategy, self.get_current_season(), limit),
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
            "SELECT total_value FROM snapshots WHERE strategy = ? AND timestamp >= ? AND season = ? "
            "ORDER BY timestamp ASC LIMIT 1",
            (strategy, since_iso, self.get_current_season()),
        ).fetchone()
        return row["total_value"] if row is not None else None

    def get_peak_value(self, strategy: str) -> float | None:
        """Highest snapshot value this season (for drawdown context)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT MAX(total_value) AS peak FROM snapshots WHERE strategy = ? AND season = ?",
            (strategy, self.get_current_season()),
        ).fetchone()
        return row["peak"]

    def get_trades_since(self, strategy: str, since_iso: str) -> list[dict[str, Any]]:
        """Trades executed for a strategy since a timestamp (fills while asleep)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT action, ticker, shares, price, reason, timestamp FROM trades "
            "WHERE strategy = ? AND season = ? AND timestamp > ? ORDER BY id ASC",
            (strategy, self.get_current_season(), since_iso),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_snapshot(self, strategy: str, timestamp: datetime, total_value: float) -> None:
        """Save a portfolio value snapshot."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO snapshots (strategy, timestamp, total_value, season) VALUES (?, ?, ?, ?)",
            (strategy, timestamp.isoformat(), total_value, self.get_current_season()),
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
               (strategy, cycle_number, timestamp, pipeline_json, llm_input_json, llm_output_json, risk_check_json, execution_json, season)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (strategy, cycle_number, timestamp, pipeline_json, llm_input_json, llm_output_json, risk_check_json, execution_json, self.get_current_season()),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def save_llm_cost(
        self, model: str, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> None:
        """Persist one LLM call's cost (survives restarts, unlike the in-memory tracker)."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO llm_costs (timestamp, model, input_tokens, output_tokens, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), model, input_tokens, output_tokens, cost_usd),
        )
        conn.commit()

    def get_llm_cost_summary(self) -> list[dict[str, Any]]:
        """Total cost and tokens per model, all time."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT model, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, "
            "SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS cost_usd "
            "FROM llm_costs GROUP BY model ORDER BY cost_usd DESC"
        ).fetchall()
        return [dict(row) for row in rows]

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
