"""Earnings and fundamental event analysis using LLM."""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from api.data.news import get_stock_news

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[float, any]] = {}
_CACHE_TTL = 60 * 60  # 1 hour

@dataclass
class EarningsInsight:
    ticker: str
    has_recent_earnings: bool
    sentiment: str  # "positive", "negative", "neutral", "unknown"
    key_points: list[str]
    forward_guidance: str  # "raised", "lowered", "maintained", "unknown"

def analyze_earnings_news(tickers: list[str]) -> dict[str, EarningsInsight]:
    """Analyze recent earnings-related news for each ticker.
    Uses Google News RSS to find earnings mentions, then summarizes.
    No LLM call — just keyword-based analysis of news headlines.
    """
    results = {}
    for ticker in tickers:
        cache_key = f"earnings_{ticker}"
        if cache_key in _cache and time.time() - _cache[cache_key][0] < _CACHE_TTL:
            results[ticker] = _cache[cache_key][1]
            continue

        news = get_stock_news(ticker, limit=10)

        # Keyword-based earnings detection
        earnings_keywords = ["earnings", "revenue", "EPS", "beat", "miss", "guidance",
                           "quarterly", "profit", "loss", "forecast", "outlook"]
        earnings_news = [n for n in news if any(kw.lower() in n.lower() for kw in earnings_keywords)]

        if not earnings_news:
            insight = EarningsInsight(
                ticker=ticker, has_recent_earnings=False,
                sentiment="unknown", key_points=[], forward_guidance="unknown"
            )
        else:
            # Simple sentiment from headlines
            positive_words = ["beat", "surge", "record", "raise", "strong", "exceed", "upbeat"]
            negative_words = ["miss", "disappoint", "cut", "lower", "weak", "decline", "warn"]

            pos_count = sum(1 for n in earnings_news for w in positive_words if w.lower() in n.lower())
            neg_count = sum(1 for n in earnings_news for w in negative_words if w.lower() in n.lower())

            sentiment = "positive" if pos_count > neg_count else "negative" if neg_count > pos_count else "neutral"

            # Guidance detection
            guidance = "unknown"
            for n in earnings_news:
                nl = n.lower()
                if "raise" in nl or "upward" in nl or "increased guidance" in nl:
                    guidance = "raised"
                elif "lower" in nl or "cut" in nl or "reduced guidance" in nl:
                    guidance = "lowered"
                elif "maintain" in nl or "reiterate" in nl or "affirm" in nl:
                    guidance = "maintained"

            insight = EarningsInsight(
                ticker=ticker, has_recent_earnings=True,
                sentiment=sentiment, key_points=earnings_news[:3], forward_guidance=guidance
            )

        _cache[cache_key] = (time.time(), insight)
        results[ticker] = insight

    return results

def format_earnings_report(insights: dict[str, EarningsInsight]) -> str:
    """Format earnings insights for LLM prompt."""
    lines = ["EARNINGS & FUNDAMENTAL EVENTS:"]
    for ticker, insight in insights.items():
        if insight.has_recent_earnings:
            emoji = {"positive": "\U0001f7e2", "negative": "\U0001f534", "neutral": "\U0001f7e1"}.get(insight.sentiment, "\u26aa")
            lines.append(f"  {emoji} {ticker}: {insight.sentiment} earnings | Guidance: {insight.forward_guidance}")
            for point in insight.key_points[:2]:
                lines.append(f"      - {point[:100]}")

    return "\n".join(lines) if len(lines) > 1 else ""
