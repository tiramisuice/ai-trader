"""News fetching via Google News RSS — free, no API key needed."""

from __future__ import annotations

import logging
import time
from typing import Any

import feedparser

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 60 * 30  # 30 minutes


def _get_cached(key: str) -> Any | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: Any) -> None:
    _cache[key] = (time.time(), data)


def get_stock_news(ticker: str, limit: int = 5) -> list[str]:
    """Get recent news headlines for a ticker via Google News RSS."""
    cache_key = f"news:{ticker}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        headlines = [entry.get("title", "") for entry in feed.entries[:limit] if entry.get("title")]
        _set_cached(cache_key, headlines)
        return headlines
    except Exception as e:
        logger.warning("Failed to fetch news for %s: %s", ticker, e)
        return []


def get_market_news(limit: int = 8) -> list[str]:
    """Get general market/finance news headlines."""
    cache_key = "market_news"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    try:
        url = "https://news.google.com/rss/search?q=stock+market+today&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        headlines = [entry.get("title", "") for entry in feed.entries[:limit] if entry.get("title")]
        _set_cached(cache_key, headlines)
        return headlines
    except Exception as e:
        logger.warning("Failed to fetch market news: %s", e)
        return []


def get_news_summary(tickers: list[str] | None = None) -> str:
    """Build a news summary string for AI trading decisions."""
    parts = []

    # Market news
    market = get_market_news()
    if market:
        parts.append("=== Market News ===")
        for h in market:
            parts.append(f"- {h}")

    # Stock-specific news
    if tickers:
        for ticker in tickers[:6]:  # Limit to avoid too many API calls
            stock_news = get_stock_news(ticker)
            if stock_news:
                parts.append(f"\n=== {ticker} News ===")
                for h in stock_news:
                    parts.append(f"- {h}")

    return "\n".join(parts) if parts else "No news available."
