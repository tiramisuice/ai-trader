"""Performance analytics API routes."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from api.db.sqlite import db
from api.quant.performance import PerformanceMetrics, compute_performance
from api.trading.portfolio import STARTING_CAPITAL
from api.trading.strategies import STRATEGY_MAP
from api.trading.strategies_tw import TW_STRATEGY_MAP

logger = logging.getLogger(__name__)
router = APIRouter()

TW_STARTING_CAPITAL = 300_000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metrics_for_strategy(strategy: str, starting_capital: float) -> dict[str, Any]:
    """Compute performance metrics for a single strategy."""
    # Get all snapshots (up to 10000 to cover long history)
    snapshots = db.get_snapshots(strategy=strategy, limit=10_000)

    # Get all trades (high limit to get full history)
    trade_records = db.get_trades(strategy=strategy, limit=10_000)
    trades = [r.model_dump(mode="json") for r in trade_records]

    metrics = compute_performance(
        snapshots=snapshots,
        trades=trades,
        starting_capital=starting_capital,
        strategy=strategy,
    )
    return asdict(metrics)


# ---------------------------------------------------------------------------
# US performance endpoints
# ---------------------------------------------------------------------------


@router.get("/api/performance")
def get_all_performance() -> list[dict[str, Any]]:
    """Get performance metrics for all US strategies."""
    results = []
    for strategy_name in STRATEGY_MAP:
        try:
            metrics = _metrics_for_strategy(strategy_name, STARTING_CAPITAL)
            # Add display info
            info = STRATEGY_MAP[strategy_name].get_info()
            metrics["display_name"] = info.display_name
            metrics["emoji"] = info.emoji
            results.append(metrics)
        except Exception as e:
            logger.error("Failed to compute performance for %s: %s", strategy_name, e)
            continue

    # Sort by total_return_pct descending
    results.sort(key=lambda x: x["total_return_pct"], reverse=True)
    return results


@router.get("/api/performance/tw")
def get_tw_performance() -> list[dict[str, Any]]:
    """Get performance metrics for all TW strategies."""
    results = []
    for strategy_name in TW_STRATEGY_MAP:
        try:
            metrics = _metrics_for_strategy(strategy_name, TW_STARTING_CAPITAL)
            info = TW_STRATEGY_MAP[strategy_name].get_info()
            metrics["display_name"] = info.display_name
            metrics["emoji"] = info.emoji
            results.append(metrics)
        except Exception as e:
            logger.error("Failed to compute TW performance for %s: %s", strategy_name, e)
            continue

    results.sort(key=lambda x: x["total_return_pct"], reverse=True)
    return results


@router.get("/api/performance/{strategy}")
def get_strategy_performance(strategy: str) -> dict[str, Any]:
    """Get detailed performance for one strategy (US or TW)."""
    if strategy in STRATEGY_MAP:
        capital = STARTING_CAPITAL
        info = STRATEGY_MAP[strategy].get_info()
    elif strategy in TW_STRATEGY_MAP:
        capital = TW_STARTING_CAPITAL
        info = TW_STRATEGY_MAP[strategy].get_info()
    else:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy}")

    metrics = _metrics_for_strategy(strategy, capital)
    metrics["display_name"] = info.display_name
    metrics["emoji"] = info.emoji
    return metrics
