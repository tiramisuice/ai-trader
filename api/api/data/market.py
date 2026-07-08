"""Market data fetching via yfinance with simple dict-based caching."""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

from api.data.fetch import fetch_history as _fetch_history, fetch_info as _fetch_info

logger = logging.getLogger(__name__)

# Simple cache: {key: (timestamp, data)}
_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 60  # seconds
_CACHE_MAX_ENTRIES = 512  # long-running process: evict instead of growing forever


def _get_cached(key: str) -> Any | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: Any) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        now = time.time()
        expired = [k for k, (ts, _) in _cache.items() if now - ts >= _CACHE_TTL]
        for k in expired:
            _cache.pop(k, None)
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            _cache.clear()
    _cache[key] = (time.time(), data)


def _rsi_14(close: pd.Series) -> float | None:
    """RSI(14) from a close series. None when there's not enough data."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
    if pd.isna(gain) or pd.isna(loss):
        return None
    if loss == 0:
        return 50.0 if gain == 0 else 100.0
    return 100 - (100 / (1 + gain / loss))


def get_price_data(ticker: str) -> dict[str, Any]:
    """Get current price data for a single ticker.

    Returns dict with: current_price, change_pct_1d, pe_ratio, market_cap, volume.
    """
    cache_key = f"price:{ticker}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        info = _fetch_info(ticker)

        current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0.0)
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose", 0.0)

        change_pct = 0.0
        if prev_close and prev_close > 0:
            change_pct = ((current_price - prev_close) / prev_close) * 100

        result = {
            "ticker": ticker,
            "current_price": round(float(current_price), 2),
            "change_pct_1d": round(change_pct, 2),
            "pe_ratio": info.get("trailingPE"),
            "market_cap": info.get("marketCap"),
            "volume": info.get("volume") or info.get("regularMarketVolume"),
        }
        _set_cached(cache_key, result)
        return result

    except Exception as e:
        logger.error("Failed to get price data for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "current_price": 0.0,
            "change_pct_1d": 0.0,
            "pe_ratio": None,
            "market_cap": None,
            "volume": None,
        }


def get_portfolio_prices(tickers: list[str]) -> dict[str, float]:
    """Get current prices for a list of tickers. Returns {ticker: price}."""
    cache_key = f"portfolio_prices:{','.join(sorted(tickers))}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    prices: dict[str, float] = {}
    for ticker in tickers:
        data = get_price_data(ticker)
        price = data["current_price"]
        # A failed/zero quote means "unknown", not "worthless" — omit it so
        # callers keep the last known price instead of marking positions to 0.
        if price and price > 0:
            prices[ticker] = price
        else:
            logger.warning("No valid price for %s — omitting from price map", ticker)

    _set_cached(cache_key, prices)
    return prices


def get_watchlist_data(tickers: list[str]) -> str:
    """Get price + RSI + SMA20 for all watchlist tickers. Returns formatted string."""
    cache_key = f"watchlist_data:{','.join(sorted(tickers))}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # Start with market indices for context
    indices = ["SPY", "QQQ", "DIA"]
    lines: list[str] = ["Market Indices:"]
    for symbol in indices:
        data = get_price_data(symbol)
        price = data["current_price"]
        change = data["change_pct_1d"]
        direction = "+" if change >= 0 else ""
        lines.append(f"  {symbol}: ${price:.2f} ({direction}{change:.2f}%)")

    lines.append("\nWatchlist Data:")
    for ticker in tickers:
        try:
            hist = _fetch_history(ticker, "1mo")
            if hist.empty:
                lines.append(f"  {ticker}: no data")
                continue

            price = hist["Close"].iloc[-1]
            sma_20 = hist["Close"].rolling(20).mean().iloc[-1] if len(hist) >= 20 else None

            rsi = _rsi_14(hist["Close"])

            vol = hist["Volume"].iloc[-1]

            # Format volume as human-readable
            if vol >= 1_000_000:
                vol_str = f"{vol / 1_000_000:.1f}M"
            elif vol >= 1_000:
                vol_str = f"{vol / 1_000:.1f}K"
            else:
                vol_str = str(int(vol))

            line = f"  {ticker}: ${price:.2f}"
            if sma_20 and not pd.isna(sma_20):
                above = "above" if price > sma_20 else "below"
                line += f" | SMA20: ${sma_20:.2f} ({above})"
            line += f" | RSI: {rsi:.0f}" if rsi is not None else " | RSI: N/A"
            line += f" | Vol: {vol_str}"
            lines.append(line)
        except Exception as e:
            logger.warning("Failed to get watchlist data for %s: %s", ticker, e)
            lines.append(f"  {ticker}: error fetching data")

    result = "\n".join(lines)
    _set_cached(cache_key, result)
    return result


def get_market_summary() -> str:
    """Get a summary string of major market indices (SPY, QQQ, DIA)."""
    cache_key = "market_summary"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    indices = ["SPY", "QQQ", "DIA"]
    lines: list[str] = []

    for symbol in indices:
        data = get_price_data(symbol)
        price = data["current_price"]
        change = data["change_pct_1d"]
        direction = "+" if change >= 0 else ""
        lines.append(f"{symbol}: ${price:.2f} ({direction}{change:.2f}%)")

    # Add top stock watchlist with basic technicals
    watchlist = ["NVDA", "TSLA", "META", "MSFT", "GOOGL", "AMZN", "AAPL"]
    lines.append("\nStock Watchlist:")
    for ticker in watchlist:
        try:
            hist = _fetch_history(ticker, "1mo")
            if not hist.empty:
                price = hist["Close"].iloc[-1]
                sma_20 = hist["Close"].rolling(20).mean().iloc[-1] if len(hist) >= 20 else None
                rsi = _rsi_14(hist["Close"])
                vol = hist["Volume"].iloc[-1]

                line = f"  {ticker}: ${price:.2f}"
                if sma_20 and not pd.isna(sma_20):
                    above = "above" if price > sma_20 else "below"
                    line += f" | SMA20: ${sma_20:.2f} ({above})"
                line += f" | RSI: {rsi:.0f}" if rsi is not None else " | RSI: N/A"
                line += f" | Vol: {vol:,.0f}"
                lines.append(line)
        except Exception as e:
            logger.warning("Failed to get market summary data for %s: %s", ticker, e)

    summary = "Market Summary:\n" + "\n".join(lines)
    _set_cached(cache_key, summary)
    return summary
