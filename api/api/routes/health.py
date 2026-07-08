"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from api.trading.scheduler import trading_scheduler

router = APIRouter()


@router.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "cycle_count": trading_scheduler.cycle_count,
        "scheduler_running": trading_scheduler.is_running,
    }
