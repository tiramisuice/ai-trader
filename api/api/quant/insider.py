"""SEC Form 4 insider trading signals via yfinance."""

from __future__ import annotations
import logging
import time
import yfinance as yf
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Simple dict cache: {cache_key: (timestamp, data)}
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 60  # seconds


def _get_cached(key: str):
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: object):
    _cache[key] = (time.time(), data)


@dataclass
class InsiderSignal:
    """Insider trading signal for a single stock."""
    ticker: str
    net_insider_buys_30d: int  # Net shares bought by insiders in last 30 days
    signal: str  # "bullish", "bearish", "neutral"
    details: list[str] = field(default_factory=list)


def _fetch_insider_data(ticker: str) -> InsiderSignal:
    """Fetch insider trading data for a single stock from yfinance."""
    try:
        stock = yf.Ticker(ticker)

        # Try insider_transactions first (more detailed)
        net_buys = 0
        details: list[str] = []
        cutoff = datetime.now() - timedelta(days=30)

        try:
            transactions = stock.insider_transactions
            if transactions is not None and not transactions.empty:
                for _, row in transactions.iterrows():
                    # Check date — yfinance may return 'Start Date' or 'startDate'
                    date_val = None
                    for date_col in ["Start Date", "startDate", "Date"]:
                        if date_col in row.index:
                            date_val = row[date_col]
                            break

                    if date_val is not None:
                        try:
                            if hasattr(date_val, 'timestamp'):
                                tx_date = date_val
                            else:
                                tx_date = datetime.strptime(str(date_val)[:10], "%Y-%m-%d")
                            if tx_date.replace(tzinfo=None) < cutoff:
                                continue
                        except (ValueError, TypeError):
                            pass  # Include if we can't parse date

                    # Parse transaction type
                    text_col = None
                    for col in ["Text", "text", "Transaction"]:
                        if col in row.index:
                            text_col = str(row[col])
                            break

                    shares_col = None
                    for col in ["Shares", "shares", "Value"]:
                        if col in row.index:
                            try:
                                shares_col = int(float(row[col]))
                            except (ValueError, TypeError):
                                pass
                            break

                    insider_col = None
                    for col in ["Insider", "insider", "Insider Trading"]:
                        if col in row.index:
                            insider_col = str(row[col])
                            break

                    if text_col:
                        text_lower = text_col.lower()
                        shares = shares_col or 0
                        if "purchase" in text_lower or "buy" in text_lower:
                            net_buys += shares
                            insider_name = insider_col or "Unknown"
                            details.append(f"BUY {shares:,} shares by {insider_name}")
                        elif "sale" in text_lower or "sell" in text_lower:
                            net_buys -= shares
                            insider_name = insider_col or "Unknown"
                            details.append(f"SELL {shares:,} shares by {insider_name}")

                if details:
                    signal = "bullish" if net_buys > 0 else ("bearish" if net_buys < 0 else "neutral")
                    return InsiderSignal(
                        ticker=ticker,
                        net_insider_buys_30d=net_buys,
                        signal=signal,
                        details=details[:10],  # Limit to 10 most recent
                    )
        except Exception as e:
            logger.debug("insider_transactions failed for %s: %s", ticker, e)

        # Try insider_purchases as fallback
        try:
            purchases = stock.insider_purchases
            if purchases is not None and not purchases.empty:
                for _, row in purchases.iterrows():
                    for col in ["Shares", "shares", "Purchases"]:
                        if col in row.index:
                            try:
                                shares = int(float(row[col]))
                                net_buys += shares
                                details.append(f"Purchase: {shares:,} shares")
                            except (ValueError, TypeError):
                                pass
                            break

                if details:
                    signal = "bullish" if net_buys > 0 else "neutral"
                    return InsiderSignal(
                        ticker=ticker,
                        net_insider_buys_30d=net_buys,
                        signal=signal,
                        details=details[:10],
                    )
        except Exception as e:
            logger.debug("insider_purchases failed for %s: %s", ticker, e)

        # No insider data available — return neutral
        return InsiderSignal(
            ticker=ticker,
            net_insider_buys_30d=0,
            signal="neutral",
            details=["No recent insider transaction data available"],
        )

    except Exception as e:
        logger.error("Failed to fetch insider data for %s: %s", ticker, e)
        return InsiderSignal(
            ticker=ticker,
            net_insider_buys_30d=0,
            signal="neutral",
            details=[f"Error fetching data: {e}"],
        )


def get_insider_signals(tickers: list[str]) -> dict[str, InsiderSignal]:
    """Get insider trading signals for stocks."""
    cache_key = "insider_" + "_".join(sorted(tickers))
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    results: dict[str, InsiderSignal] = {}
    for t in tickers:
        results[t] = _fetch_insider_data(t)

    _set_cached(cache_key, results)
    return results


def format_insider_report(signals: dict[str, InsiderSignal]) -> str:
    """Format insider signals into readable text for LLM prompt."""
    if not signals:
        return "No insider data available."

    parts = ["INSIDER TRADING SIGNALS (Last 30 Days)", "=" * 50, ""]

    for t, sig in sorted(signals.items()):
        icon = {"bullish": "+", "bearish": "-", "neutral": "~"}.get(sig.signal, "?")
        parts.append(f"  [{icon}] {sig.ticker}: {sig.signal.upper()} (net {sig.net_insider_buys_30d:+,} shares)")
        for detail in sig.details:
            parts.append(f"      {detail}")

    return "\n".join(parts)
