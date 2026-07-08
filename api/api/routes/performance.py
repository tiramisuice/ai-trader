"""Performance analytics API routes."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from api.data.fetch import fetch_history
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


@router.get("/api/performance/llm-costs")
def get_llm_costs() -> dict[str, Any]:
    """LLM spend per model (persisted — survives restarts)."""
    per_model = db.get_llm_cost_summary()
    return {
        "per_model": per_model,
        "total_cost_usd": round(sum(m["cost_usd"] or 0 for m in per_model), 4),
        "total_calls": sum(m["calls"] or 0 for m in per_model),
    }


@router.get("/api/performance/benchmark/{strategy}")
def get_strategy_benchmark(strategy: str) -> dict[str, Any]:
    """Compare a strategy against buy-and-hold of its market benchmark
    (SPY for US, 0050.TW for TW) over the same period."""
    if strategy in STRATEGY_MAP:
        benchmark_ticker = "SPY"
    elif strategy in TW_STRATEGY_MAP:
        benchmark_ticker = "0050.TW"
    else:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy}")

    snapshots = db.get_snapshots(strategy=strategy, limit=10_000)
    if len(snapshots) < 2:
        raise HTTPException(status_code=404, detail=f"Not enough history for {strategy}")

    start_value = snapshots[0]["total_value"]
    end_value = snapshots[-1]["total_value"]
    start_date = snapshots[0]["timestamp"][:10]
    end_date = snapshots[-1]["timestamp"][:10]
    strategy_return_pct = round((end_value / start_value - 1) * 100, 2)

    try:
        hist = fetch_history(benchmark_ticker, "2y")
        window = hist.loc[start_date:end_date]
        if len(window) < 2:
            raise ValueError(f"no benchmark data in window {start_date}..{end_date}")
        bench_start = float(window["Close"].iloc[0])
        bench_end = float(window["Close"].iloc[-1])
        benchmark_return_pct = round((bench_end / bench_start - 1) * 100, 2)
    except Exception as e:
        logger.error("Benchmark fetch failed for %s: %s", benchmark_ticker, e)
        raise HTTPException(status_code=502, detail=f"Benchmark data unavailable: {e}")

    return {
        "strategy": strategy,
        "period": {"start": start_date, "end": end_date},
        "strategy_return_pct": strategy_return_pct,
        "benchmark": benchmark_ticker,
        "benchmark_return_pct": benchmark_return_pct,
        "alpha_pct": round(strategy_return_pct - benchmark_return_pct, 2),
    }


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
