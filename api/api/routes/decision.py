"""Decision flow API — exposes the full decision pipeline for each strategy."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.db.sqlite import db

router = APIRouter()


@router.get("/api/decision/{strategy}")
def get_decision_flow(strategy: str) -> dict[str, Any]:
    """Get the full decision pipeline from the latest cycle."""
    row = db.get_latest_decision_log(strategy)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No decision data for strategy '{strategy}'. Run a trading cycle first.",
        )
    return row


@router.get("/api/decision/{strategy}/history")
def get_decision_history(
    strategy: str,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict[str, Any]]:
    """Get decision flow history for a strategy."""
    return db.get_decision_log_history(strategy, limit)
