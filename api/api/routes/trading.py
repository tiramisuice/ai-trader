"""Trading-related API routes: strategies, cycle control, scheduler status."""

from __future__ import annotations

import logging
import traceback
from typing import Any

from fastapi import APIRouter, HTTPException

from api.db.sqlite import db
from api.trading.scheduler import trading_scheduler
from api.trading.strategies import ALL_STRATEGIES
from api.trading.strategies_tw import ALL_TW_STRATEGIES

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/strategies")
def list_strategies() -> list[dict[str, Any]]:
    """List all 5 US trading strategies with their info."""
    return [s.get_info().model_dump() for s in ALL_STRATEGIES]


@router.get("/api/strategies/tw")
def list_tw_strategies() -> list[dict[str, Any]]:
    """List all 5 Taiwan trading strategies with their info."""
    return [s.get_info().model_dump() for s in ALL_TW_STRATEGIES]


@router.post("/api/cycle")
def trigger_cycle() -> dict[str, Any]:
    """Manually trigger one US trading cycle and return results."""
    try:
        results = trading_scheduler.run_cycle_now()
        return {
            "status": "completed",
            "market": "us",
            "cycle_count": trading_scheduler.cycle_count,
            "results": results,
        }
    except Exception as e:
        logger.error("US Cycle failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/cycle/tw")
def trigger_tw_cycle() -> dict[str, Any]:
    """Manually trigger one Taiwan trading cycle and return results."""
    try:
        results = trading_scheduler.run_tw_cycle_now()
        return {
            "status": "completed",
            "market": "tw",
            "cycle_count": trading_scheduler.tw_cycle_count,
            "results": results,
        }
    except Exception as e:
        logger.error("TW Cycle failed: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/status")
def scheduler_status() -> dict[str, Any]:
    """Get the current scheduler status for both US and TW markets."""
    return {
        "running": trading_scheduler.is_running,
        "season": db.get_current_season(),
        "agents": trading_scheduler.get_agent_states(),
        "us": {
            "cycle_count": trading_scheduler.cycle_count,
            "next_run_time": trading_scheduler.get_next_run_time(),
            "last_cycle_results": trading_scheduler.last_cycle_results,
        },
        "tw": {
            "cycle_count": trading_scheduler.tw_cycle_count,
            "next_run_time": trading_scheduler.get_tw_next_run_time(),
            "last_cycle_results": trading_scheduler.last_tw_cycle_results,
        },
    }


@router.post("/api/start")
def start_scheduler() -> dict[str, str]:
    """Start the automatic trading scheduler."""
    if trading_scheduler.is_running:
        return {"status": "already_running"}
    trading_scheduler.start()
    return {"status": "started"}


@router.post("/api/stop")
def stop_scheduler() -> dict[str, str]:
    """Stop the automatic trading scheduler."""
    if not trading_scheduler.is_running:
        return {"status": "already_stopped"}
    trading_scheduler.stop()
    return {"status": "stopped"}
