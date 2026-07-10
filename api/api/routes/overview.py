"""Agent overview and per-stock detail endpoints for the soul-era UI."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.data.fetch import fetch_history, fetch_info
from api.db.sqlite import db
from api.trading.scheduler import trading_scheduler
from api.trading.strategies import STRATEGY_MAP
from api.trading.strategies_tw import TW_STRATEGY_MAP

logger = logging.getLogger(__name__)
router = APIRouter()

_stock_cache: dict[str, tuple[float, Any]] = {}
_STOCK_CACHE_TTL = 300  # 5 minutes


@router.get("/api/overview")
def get_overview(market: str = Query(default="us")) -> list[dict[str, Any]]:
    """Everything needed to see how each agent is doing right now, in one call:
    value/return, sleep schedule, standing intents, latest journal entry, and
    an equity sparkline."""
    strategy_map = TW_STRATEGY_MAP if market == "tw" else STRATEGY_MAP
    portfolios = (
        trading_scheduler.get_tw_portfolios() if market == "tw"
        else trading_scheduler.get_portfolios()
    )
    if not portfolios:
        trading_scheduler.initialize()
        portfolios = (
            trading_scheduler.get_tw_portfolios() if market == "tw"
            else trading_scheduler.get_portfolios()
        )

    results = []
    for name, strategy in strategy_map.items():
        portfolio = portfolios.get(name)
        if not portfolio:
            continue
        info = strategy.get_info()
        agent_state = db.get_agent_state(name) or {}
        journal = db.get_recent_journal(name, limit=1)
        snapshots = db.get_snapshots(name, limit=120)
        intents = db.get_active_intents(name)

        results.append({
            "strategy": name,
            "display_name": info.display_name,
            "emoji": info.emoji,
            "model": info.model,
            "style": info.style,
            "currency": portfolio.currency,
            "total_value": round(portfolio.total_value, 2),
            "return_pct": portfolio.total_return_pct,
            "cash": round(portfolio.cash, 2),
            "positions": [
                {
                    "ticker": t,
                    "shares": p.shares,
                    "pnl_pct": round(((p.current_price - p.avg_cost) / p.avg_cost) * 100, 2)
                    if p.avg_cost > 0 else 0.0,
                }
                for t, p in portfolio.positions.items()
            ],
            "next_wakeup": agent_state.get("next_wakeup"),
            "watchlist_size": len(agent_state.get("watchlist", [])),
            "intents": [
                {
                    "kind": i["kind"], "action": i.get("action"), "ticker": i["ticker"],
                    "shares": i.get("shares"), "trigger_type": i["trigger_type"],
                    "trigger_price": i["trigger_price"], "reason": i.get("reason", ""),
                    "expires_at": i["expires_at"],
                }
                for i in intents
            ],
            "last_journal": journal[-1] if journal else None,
            "sparkline": [
                {"t": s["timestamp"], "v": s["total_value"]} for s in snapshots
            ],
        })

    results.sort(key=lambda x: x["total_value"], reverse=True)
    return results


@router.get("/api/stock/{ticker}")
def get_stock_detail(ticker: str, range_: str = Query(default="6mo", alias="range")) -> dict[str, Any]:
    """Everything about one stock: quote, key stats, price chart, which agents
    hold it, recent trades on it, and standing intents that reference it."""
    ticker = ticker.upper()
    if range_ not in ("1mo", "3mo", "6mo", "1y", "2y"):
        raise HTTPException(status_code=400, detail=f"Bad range: {range_}")

    cache_key = f"{ticker}:{range_}"
    cached = _stock_cache.get(cache_key)
    market_part: dict[str, Any]
    if cached and time.time() - cached[0] < _STOCK_CACHE_TTL:
        market_part = cached[1]
    else:
        try:
            hist = fetch_history(ticker, "1y" if range_ in ("1mo", "3mo", "6mo") else range_)
            closes = hist["Close"].dropna()
            if closes.empty:
                raise ValueError("no price data")
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"No data for {ticker}: {e}")

        info: dict[str, Any] = {}
        try:
            info = fetch_info(ticker)
        except Exception as e:
            logger.warning("info fetch failed for %s: %s", ticker, e)

        price = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) >= 2 else price
        sma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
        sma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
        delta = closes.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = None
        if not (gain != gain or loss != loss):  # NaN check
            rsi = 50.0 if loss == 0 and gain == 0 else (100.0 if loss == 0 else float(100 - 100 / (1 + gain / loss)))

        days = {"1mo": 22, "3mo": 66, "6mo": 126, "1y": 252, "2y": 504}[range_]
        window = closes.tail(days)
        market_part = {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "quote": {
                "price": round(price, 2),
                "day_change_pct": round((price / prev - 1) * 100, 2) if prev > 0 else 0.0,
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
            },
            "stats": {
                "high_52w": round(float(closes.tail(252).max()), 2),
                "low_52w": round(float(closes.tail(252).min()), 2),
                "sma20": round(sma20, 2) if sma20 else None,
                "sma50": round(sma50, 2) if sma50 else None,
                "rsi14": round(rsi, 1) if rsi is not None else None,
                "return_range_pct": round((price / float(window.iloc[0]) - 1) * 100, 2) if len(window) else 0.0,
            },
            "chart": [
                {"date": d.strftime("%Y-%m-%d"), "close": round(float(v), 2)}
                for d, v in window.items()
            ],
        }
        _stock_cache[cache_key] = (time.time(), market_part)
        if len(_stock_cache) > 128:
            _stock_cache.clear()

    # Live parts (never cached): holders, trades, intents
    holders = []
    all_portfolios = {**trading_scheduler.get_portfolios(), **trading_scheduler.get_tw_portfolios()}
    all_info = {**STRATEGY_MAP, **TW_STRATEGY_MAP}
    for name, portfolio in all_portfolios.items():
        pos = portfolio.positions.get(ticker)
        if pos:
            info_s = all_info[name].get_info()
            holders.append({
                "strategy": name,
                "display_name": info_s.display_name,
                "emoji": info_s.emoji,
                "market": info_s.market,
                "shares": pos.shares,
                "avg_cost": round(pos.avg_cost, 2),
                "pnl_pct": round(((pos.current_price - pos.avg_cost) / pos.avg_cost) * 100, 2)
                if pos.avg_cost > 0 else 0.0,
            })

    trades = [
        r.model_dump(mode="json")
        for r in db.get_trades(limit=500)
        if r.ticker == ticker
    ][:30]

    intents = [
        {
            "strategy": i["strategy"], "kind": i["kind"], "action": i.get("action"),
            "shares": i.get("shares"), "trigger_type": i["trigger_type"],
            "trigger_price": i["trigger_price"], "reason": i.get("reason", ""),
        }
        for i in db.get_active_intents()
        if i["ticker"] == ticker
    ]

    return {**market_part, "holders": holders, "recent_trades": trades, "intents": intents}
