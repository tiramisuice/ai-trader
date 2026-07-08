"""Multi-factor stock scoring model — Fama-French style factor scores."""

from __future__ import annotations
import logging
import time
import numpy as np
from dataclasses import dataclass

from api.data.fetch import fetch_history, fetch_info

logger = logging.getLogger(__name__)

# Simple dict cache: {cache_key: (timestamp, data)}
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 60  # seconds


def _get_cached(key: str):
    """Return cached data if still fresh, else None."""
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: object):
    _cache[key] = (time.time(), data)


@dataclass
class FactorScores:
    """Factor scores for a single stock (z-scores, higher = better)."""
    ticker: str
    # Individual factors (z-scores)
    value_score: float
    momentum_score: float
    quality_score: float
    size_score: float
    volatility_score: float
    # Composite
    composite_score: float  # Average of all factor z-scores
    factor_signal: str  # "strong_buy", "buy", "neutral", "sell", "strong_sell"
    # Raw data for transparency
    earnings_yield: float | None
    book_to_market: float | None
    roe: float | None
    profit_margin: float | None
    debt_to_equity: float | None
    market_cap: float | None
    momentum_12_1: float | None
    momentum_6_1: float | None
    volatility_60d: float | None


def _safe_get(info: dict, key: str) -> float | None:
    """Safely get a numeric value from yfinance info dict."""
    val = info.get(key)
    if val is None:
        return None
    try:
        f = float(val)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (ValueError, TypeError):
        return None


def _fetch_raw_factors(ticker: str) -> dict | None:
    """Fetch raw factor data for a single stock from yfinance."""
    try:
        info = fetch_info(ticker)
        hist = fetch_history(ticker, "1y")

        if hist.empty or len(hist) < 60:
            logger.warning("Insufficient history for %s (%d rows)", ticker, len(hist))
            return None

        close = hist["Close"]
        price = float(close.iloc[-1])

        # --- Value Factor raw data ---
        eps = _safe_get(info, "trailingEps")
        earnings_yield = (eps / price) if (eps is not None and price > 0) else None

        book_value = _safe_get(info, "bookValue")
        market_cap = _safe_get(info, "marketCap")
        shares_outstanding = _safe_get(info, "sharesOutstanding")
        # Book-to-Market = (bookValue * sharesOutstanding) / marketCap
        if book_value is not None and shares_outstanding is not None and market_cap and market_cap > 0:
            book_to_market = (book_value * shares_outstanding) / market_cap
        elif book_value is not None and price > 0:
            # Fallback: bookValue / price (per-share version)
            book_to_market = book_value / price
        else:
            book_to_market = None

        # --- Momentum Factor raw data ---
        # 12-1 month momentum: return over past 12 months, skip last month
        momentum_12_1 = None
        momentum_6_1 = None
        if len(close) >= 252:
            price_12m_ago = float(close.iloc[-252])
            price_1m_ago = float(close.iloc[-21])
            if price_12m_ago > 0:
                momentum_12_1 = (price_1m_ago - price_12m_ago) / price_12m_ago
        elif len(close) >= 21:
            # Use whatever we have, minus the last month
            price_start = float(close.iloc[0])
            price_1m_ago = float(close.iloc[-21])
            if price_start > 0:
                momentum_12_1 = (price_1m_ago - price_start) / price_start

        if len(close) >= 126:
            price_6m_ago = float(close.iloc[-126])
            price_1m_ago = float(close.iloc[-21])
            if price_6m_ago > 0:
                momentum_6_1 = (price_1m_ago - price_6m_ago) / price_6m_ago

        # --- Quality Factor raw data ---
        roe = _safe_get(info, "returnOnEquity")
        profit_margin = _safe_get(info, "profitMargins")
        debt_to_equity = _safe_get(info, "debtToEquity")
        # Convert D/E from percentage (yfinance sometimes returns %) to ratio
        if debt_to_equity is not None and debt_to_equity > 10:
            debt_to_equity = debt_to_equity / 100.0

        # --- Size Factor raw data ---
        # market_cap already fetched above

        # --- Volatility Factor raw data ---
        returns = close.pct_change().dropna()
        volatility_60d = None
        if len(returns) >= 60:
            volatility_60d = float(returns.tail(60).std()) * np.sqrt(252)  # Annualized

        return {
            "ticker": ticker,
            "earnings_yield": earnings_yield,
            "book_to_market": book_to_market,
            "momentum_12_1": momentum_12_1,
            "momentum_6_1": momentum_6_1,
            "roe": roe,
            "profit_margin": profit_margin,
            "debt_to_equity": debt_to_equity,
            "market_cap": market_cap,
            "volatility_60d": volatility_60d,
        }
    except Exception as e:
        logger.error("Failed to fetch factors for %s: %s", ticker, e)
        return None


def _zscore(values: list[float | None]) -> list[float]:
    """Compute z-scores for a list, treating None as 0 (neutral).

    Returns z-scores where higher = better.
    """
    # Replace None with NaN for computation
    arr = np.array([v if v is not None else np.nan for v in values], dtype=float)
    valid = ~np.isnan(arr)

    if valid.sum() < 2:
        # Not enough data for meaningful z-scores
        return [0.0] * len(values)

    mean = float(np.nanmean(arr))
    std = float(np.nanstd(arr))

    if std < 1e-10:
        return [0.0] * len(values)

    result = []
    for v in values:
        if v is None:
            result.append(0.0)
        else:
            result.append((v - mean) / std)
    return result


def _classify_factor_signal(composite: float) -> str:
    """Classify composite factor score into a signal."""
    if composite >= 1.0:
        return "strong_buy"
    elif composite >= 0.3:
        return "buy"
    elif composite <= -1.0:
        return "strong_sell"
    elif composite <= -0.3:
        return "sell"
    else:
        return "neutral"


def compute_factor_scores(tickers: list[str]) -> dict[str, FactorScores]:
    """Compute factor scores for a batch of stocks.

    Factors are cross-sectionally z-scored (ranked among the batch).
    """
    cache_key = "factors_" + "_".join(sorted(tickers))
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # Step 1: Fetch raw factor data for all tickers
    raw_data: list[dict] = []
    valid_tickers: list[str] = []
    for t in tickers:
        data = _fetch_raw_factors(t)
        if data is not None:
            raw_data.append(data)
            valid_tickers.append(t)

    if not raw_data:
        return {}

    n = len(raw_data)

    # Step 2: Compute cross-sectional z-scores for each factor

    # --- Value Factor ---
    # Earnings yield: higher = better
    ey_zscores = _zscore([d["earnings_yield"] for d in raw_data])
    # Book-to-market: higher = better (cheaper)
    bm_zscores = _zscore([d["book_to_market"] for d in raw_data])
    # Value = average of the two
    value_scores = [(ey_zscores[i] + bm_zscores[i]) / 2 for i in range(n)]

    # --- Momentum Factor ---
    # 12-1 month momentum: higher = better
    mom12_zscores = _zscore([d["momentum_12_1"] for d in raw_data])
    # 6-1 month momentum: higher = better
    mom6_zscores = _zscore([d["momentum_6_1"] for d in raw_data])
    momentum_scores = [(mom12_zscores[i] + mom6_zscores[i]) / 2 for i in range(n)]

    # --- Quality Factor ---
    # ROE: higher = better
    roe_zscores = _zscore([d["roe"] for d in raw_data])
    # Profit margin: higher = better
    pm_zscores = _zscore([d["profit_margin"] for d in raw_data])
    # Debt-to-equity: lower = better, so negate
    de_raw = [d["debt_to_equity"] for d in raw_data]
    de_negated = [(-v if v is not None else None) for v in de_raw]
    de_zscores = _zscore(de_negated)
    quality_scores = [(roe_zscores[i] + pm_zscores[i] + de_zscores[i]) / 3 for i in range(n)]

    # --- Size Factor ---
    # Smaller = higher expected return historically, so negate market cap
    mc_raw = [d["market_cap"] for d in raw_data]
    # Use log(market_cap) for more normal distribution, then negate
    mc_log_neg = []
    for mc in mc_raw:
        if mc is not None and mc > 0:
            mc_log_neg.append(-np.log(mc))
        else:
            mc_log_neg.append(None)
    size_scores = _zscore(mc_log_neg)

    # --- Volatility Factor ---
    # Lower volatility = better historically, so negate
    vol_raw = [d["volatility_60d"] for d in raw_data]
    vol_negated = [(-v if v is not None else None) for v in vol_raw]
    volatility_scores = _zscore(vol_negated)

    # Step 3: Composite score = equal-weighted average of all factors
    results: dict[str, FactorScores] = {}
    for i, t in enumerate(valid_tickers):
        composite = (
            value_scores[i]
            + momentum_scores[i]
            + quality_scores[i]
            + size_scores[i]
            + volatility_scores[i]
        ) / 5.0

        results[t] = FactorScores(
            ticker=t,
            value_score=round(value_scores[i], 3),
            momentum_score=round(momentum_scores[i], 3),
            quality_score=round(quality_scores[i], 3),
            size_score=round(size_scores[i], 3),
            volatility_score=round(volatility_scores[i], 3),
            composite_score=round(composite, 3),
            factor_signal=_classify_factor_signal(composite),
            earnings_yield=raw_data[i]["earnings_yield"],
            book_to_market=raw_data[i]["book_to_market"],
            roe=raw_data[i]["roe"],
            profit_margin=raw_data[i]["profit_margin"],
            debt_to_equity=raw_data[i]["debt_to_equity"],
            market_cap=raw_data[i]["market_cap"],
            momentum_12_1=raw_data[i]["momentum_12_1"],
            momentum_6_1=raw_data[i]["momentum_6_1"],
            volatility_60d=raw_data[i]["volatility_60d"],
        )

    _set_cached(cache_key, results)
    return results


def format_factor_report(scores: dict[str, FactorScores]) -> str:
    """Format factor scores into readable text for LLM prompt."""
    if not scores:
        return "No factor data available."

    sorted_scores = sorted(scores.values(), key=lambda s: s.composite_score, reverse=True)

    parts = ["MULTI-FACTOR SCORE REPORT", "=" * 60, ""]

    # Summary table
    parts.append("RANKING (by composite factor score):")
    parts.append(f"  {'Ticker':<8} {'Composite':>9} {'Value':>7} {'Mom':>7} {'Quality':>8} {'Size':>7} {'Vol':>7}  Signal")
    parts.append(f"  {'-'*8} {'-'*9} {'-'*7} {'-'*7} {'-'*8} {'-'*7} {'-'*7}  {'-'*11}")

    for s in sorted_scores:
        parts.append(
            f"  {s.ticker:<8} {s.composite_score:>+9.3f} {s.value_score:>+7.3f} "
            f"{s.momentum_score:>+7.3f} {s.quality_score:>+8.3f} {s.size_score:>+7.3f} "
            f"{s.volatility_score:>+7.3f}  {s.factor_signal.upper()}"
        )

    parts.append("")
    parts.append("FACTOR DETAILS:")

    for s in sorted_scores:
        parts.append(f"\n  {s.ticker} [{s.factor_signal.upper()}] composite={s.composite_score:+.3f}")

        # Value
        ey_str = f"{s.earnings_yield:.2%}" if s.earnings_yield is not None else "N/A"
        bm_str = f"{s.book_to_market:.3f}" if s.book_to_market is not None else "N/A"
        parts.append(f"    Value (z={s.value_score:+.3f}): EY={ey_str}, B/M={bm_str}")

        # Momentum
        m12_str = f"{s.momentum_12_1:.1%}" if s.momentum_12_1 is not None else "N/A"
        m6_str = f"{s.momentum_6_1:.1%}" if s.momentum_6_1 is not None else "N/A"
        parts.append(f"    Momentum (z={s.momentum_score:+.3f}): 12-1m={m12_str}, 6-1m={m6_str}")

        # Quality
        roe_str = f"{s.roe:.1%}" if s.roe is not None else "N/A"
        pm_str = f"{s.profit_margin:.1%}" if s.profit_margin is not None else "N/A"
        de_str = f"{s.debt_to_equity:.2f}" if s.debt_to_equity is not None else "N/A"
        parts.append(f"    Quality (z={s.quality_score:+.3f}): ROE={roe_str}, Margin={pm_str}, D/E={de_str}")

        # Size
        mc_str = f"${s.market_cap / 1e9:.1f}B" if s.market_cap is not None else "N/A"
        parts.append(f"    Size (z={s.size_score:+.3f}): MCap={mc_str}")

        # Volatility
        vol_str = f"{s.volatility_60d:.1%}" if s.volatility_60d is not None else "N/A"
        parts.append(f"    Volatility (z={s.volatility_score:+.3f}): 60d ann.vol={vol_str}")

    return "\n".join(parts)
