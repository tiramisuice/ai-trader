"""Portfolio and trade history API routes."""

from __future__ import annotations

import logging
import time
from typing import Any

import yfinance as yf
from fastapi import APIRouter, HTTPException, Query

from api.db.sqlite import db
from api.trading.scheduler import trading_scheduler
from api.trading.strategies import STRATEGY_MAP
from api.trading.strategies_tw import TW_STRATEGY_MAP

logger = logging.getLogger(__name__)
router = APIRouter()

# Cache for position chart data: {key: (timestamp, data)}
_positions_cache: dict[str, tuple[float, Any]] = {}
_POSITIONS_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Helper: build positions detail for any portfolio
# ---------------------------------------------------------------------------

def _build_positions_detail(
    strategy: str, portfolio: Any, cache_prefix: str
) -> dict[str, Any]:
    """Shared logic for building position detail with chart data."""
    state = portfolio.get_state()

    if not state.positions:
        return {"strategy": strategy, "positions": []}

    # Check cache
    cache_key = f"{cache_prefix}:{strategy}"
    if cache_key in _positions_cache:
        ts, cached_data = _positions_cache[cache_key]
        if time.time() - ts < _POSITIONS_CACHE_TTL:
            return cached_data

    positions_detail: list[dict[str, Any]] = []

    for ticker, position in state.positions.items():
        pos_data: dict[str, Any] = {
            "ticker": ticker,
            "shares": position.shares,
            "avg_cost": round(position.avg_cost, 2),
            "current_price": round(position.current_price, 2),
            "unrealized_pnl": round(
                (position.current_price - position.avg_cost) * position.shares, 2
            ),
            "pnl_pct": round(
                ((position.current_price - position.avg_cost) / position.avg_cost) * 100, 2
            ) if position.avg_cost > 0 else 0.0,
            "day_change_pct": 0.0,
            "chart_data": [],
        }

        # Fetch 30-day history for chart
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1mo")
            if not hist.empty:
                # Day change
                if len(hist) >= 2:
                    prev_close = hist["Close"].iloc[-2]
                    curr_close = hist["Close"].iloc[-1]
                    if prev_close > 0:
                        pos_data["day_change_pct"] = round(
                            ((curr_close - prev_close) / prev_close) * 100, 2
                        )

                # Chart data
                chart_data: list[dict[str, Any]] = []
                for date, row in hist.iterrows():
                    chart_data.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "close": round(float(row["Close"]), 2),
                    })
                pos_data["chart_data"] = chart_data
        except Exception as e:
            logger.warning("Failed to get chart data for %s: %s", ticker, e)

        positions_detail.append(pos_data)

    result = {"strategy": strategy, "positions": positions_detail}

    # Cache the result
    _positions_cache[cache_key] = (time.time(), result)

    return result


# ---------------------------------------------------------------------------
# US portfolio endpoints
# ---------------------------------------------------------------------------


@router.get("/api/portfolios")
def all_portfolios() -> list[dict[str, Any]]:
    """Get all 5 US portfolio states (leaderboard data)."""
    portfolios = trading_scheduler.get_portfolios()

    # If scheduler hasn't initialized yet, initialize from DB
    if not portfolios:
        trading_scheduler.initialize()
        portfolios = trading_scheduler.get_portfolios()

    results = []
    for strategy_name in STRATEGY_MAP:
        portfolio = portfolios.get(strategy_name)
        if portfolio:
            state = portfolio.get_state()
            info = STRATEGY_MAP[strategy_name].get_info()
            results.append(
                {
                    **state.model_dump(mode="json"),
                    "display_name": info.display_name,
                    "emoji": info.emoji,
                    "description": info.description,
                    "model": info.model,
                    "style": info.style,
                }
            )

    # Sort by total_value descending (leaderboard)
    results.sort(key=lambda x: x["total_value"], reverse=True)
    return results


@router.get("/api/trades")
def get_trades(
    strategy: str | None = Query(default=None),
    market: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Get trade history, optionally filtered by strategy or market."""
    records = db.get_trades(strategy=strategy, limit=limit)
    # Filter by market if specified
    if market == "tw":
        records = [r for r in records if r.strategy.startswith("tw_")]
    elif market == "us":
        records = [r for r in records if not r.strategy.startswith("tw_")]
    return [r.model_dump(mode="json") for r in records]


@router.get("/api/snapshots/{strategy}")
def get_snapshots(
    strategy: str,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Get portfolio value snapshots for charting."""
    if strategy not in STRATEGY_MAP and strategy not in TW_STRATEGY_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy}")
    return db.get_snapshots(strategy=strategy, limit=limit)


# ---------------------------------------------------------------------------
# Taiwan (TW) portfolio endpoints  —  MUST be registered BEFORE the
# parameterized /api/portfolios/{strategy} routes so FastAPI matches
# the literal "/tw" path segment first.
# ---------------------------------------------------------------------------


@router.get("/api/portfolios/tw")
def all_tw_portfolios() -> list[dict[str, Any]]:
    """Get all 5 TW portfolio states (leaderboard data)."""
    portfolios = trading_scheduler.get_tw_portfolios()

    # If scheduler hasn't initialized yet, initialize from DB
    if not portfolios:
        trading_scheduler.initialize()
        portfolios = trading_scheduler.get_tw_portfolios()

    results = []
    for strategy_name in TW_STRATEGY_MAP:
        portfolio = portfolios.get(strategy_name)
        if portfolio:
            state = portfolio.get_state()
            info = TW_STRATEGY_MAP[strategy_name].get_info()
            results.append(
                {
                    **state.model_dump(mode="json"),
                    "display_name": info.display_name,
                    "emoji": info.emoji,
                    "description": info.description,
                    "model": info.model,
                    "style": info.style,
                }
            )

    # Sort by total_value descending (leaderboard)
    results.sort(key=lambda x: x["total_value"], reverse=True)
    return results


@router.get("/api/portfolios/tw/{strategy}")
def get_tw_portfolio(strategy: str) -> dict[str, Any]:
    """Get detailed portfolio for one TW strategy."""
    if strategy not in TW_STRATEGY_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown TW strategy: {strategy}")

    portfolio = trading_scheduler.get_tw_portfolio(strategy)
    if not portfolio:
        trading_scheduler.initialize()
        portfolio = trading_scheduler.get_tw_portfolio(strategy)

    if not portfolio:
        raise HTTPException(status_code=404, detail=f"TW Portfolio not found for {strategy}")

    state = portfolio.get_state()
    info = TW_STRATEGY_MAP[strategy].get_info()
    return {
        **state.model_dump(mode="json"),
        "display_name": info.display_name,
        "emoji": info.emoji,
        "description": info.description,
        "model": info.model,
        "style": info.style,
    }


@router.get("/api/portfolios/tw/{strategy}/positions")
def get_tw_positions_detail(strategy: str) -> dict[str, Any]:
    """Get detailed TW position data with 30-day price history for charts."""
    if strategy not in TW_STRATEGY_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown TW strategy: {strategy}")

    portfolio = trading_scheduler.get_tw_portfolio(strategy)
    if not portfolio:
        trading_scheduler.initialize()
        portfolio = trading_scheduler.get_tw_portfolio(strategy)

    if not portfolio:
        raise HTTPException(status_code=404, detail=f"TW Portfolio not found for {strategy}")

    return _build_positions_detail(strategy, portfolio, "positions_detail_tw")


# ---------------------------------------------------------------------------
# US parameterized endpoints  —  AFTER TW literal routes
# ---------------------------------------------------------------------------


@router.get("/api/portfolios/{strategy}")
def get_portfolio(strategy: str) -> dict[str, Any]:
    """Get detailed portfolio for one US strategy."""
    if strategy not in STRATEGY_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy}")

    portfolio = trading_scheduler.get_portfolio(strategy)
    if not portfolio:
        trading_scheduler.initialize()
        portfolio = trading_scheduler.get_portfolio(strategy)

    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio not found for {strategy}")

    state = portfolio.get_state()
    info = STRATEGY_MAP[strategy].get_info()
    return {
        **state.model_dump(mode="json"),
        "display_name": info.display_name,
        "emoji": info.emoji,
        "description": info.description,
        "model": info.model,
        "style": info.style,
    }


@router.get("/api/portfolios/{strategy}/positions")
def get_positions_detail(strategy: str) -> dict[str, Any]:
    """Get detailed position data with 30-day price history for charts."""
    if strategy not in STRATEGY_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy}")

    portfolio = trading_scheduler.get_portfolio(strategy)
    if not portfolio:
        trading_scheduler.initialize()
        portfolio = trading_scheduler.get_portfolio(strategy)

    if not portfolio:
        raise HTTPException(status_code=404, detail=f"Portfolio not found for {strategy}")

    return _build_positions_detail(strategy, portfolio, "positions_detail")
