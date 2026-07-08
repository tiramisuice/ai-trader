"""ML Signal Combiner — combines technical signals, factor scores, and other data.

Initially uses weighted rule-based combination.
After collecting enough historical data, switches to XGBoost.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from scipy.stats import norm

from api.quant.signals import TechnicalSignals
from api.quant.factors import FactorScores
from api.quant.insider import InsiderSignal

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


# ---------------------------------------------------------------------------
# Rule-based weights (used until we have enough data for XGBoost)
# ---------------------------------------------------------------------------
WEIGHT_TECHNICAL = 0.30
WEIGHT_FACTOR = 0.40
WEIGHT_INSIDER = 0.15
WEIGHT_REGIME = 0.15

MAX_POSITION_WEIGHT = 0.20  # Max 20% per stock


@dataclass
class CombinedScore:
    """Combined signal output for a single stock."""
    ticker: str
    technical_score: float   # From signals.py (-10 to 10), normalized to 0-1
    factor_score: float      # From factors.py (z-score), normalized to 0-1 via CDF
    insider_score: float     # From insider.py: bullish=1, neutral=0.5, bearish=0
    regime_scale: float      # From regime.py (0.2 to 1.0)

    combined_score: float    # Final combined score (0-1)
    rank: int                # Rank among batch (1 = best)
    signal: str              # "strong_buy", "buy", "neutral", "sell", "strong_sell"
    confidence: float        # 0-1

    suggested_weight: float  # Suggested portfolio weight (0-1)


def _normalize_technical(score: int) -> float:
    """Normalize technical score from [-10, 10] to [0, 1]."""
    return (score + 10) / 20.0


def _normalize_factor(z_score: float) -> float:
    """Normalize factor composite z-score to [0, 1] using normal CDF."""
    return float(norm.cdf(z_score))


def _normalize_insider(signal: str) -> float:
    """Convert insider signal string to numeric score."""
    mapping = {"bullish": 1.0, "neutral": 0.5, "bearish": 0.0}
    return mapping.get(signal, 0.5)


def _classify_combined(score: float) -> str:
    """Classify combined score (0-1) into a signal label."""
    if score >= 0.75:
        return "strong_buy"
    elif score >= 0.60:
        return "buy"
    elif score <= 0.25:
        return "strong_sell"
    elif score <= 0.40:
        return "sell"
    else:
        return "neutral"


def _compute_confidence(score: float) -> float:
    """Confidence = how far from neutral (0.5). Range: 0-1."""
    return min(1.0, abs(score - 0.5) * 2)


def combine_signals(
    technical: dict[str, TechnicalSignals],
    factors: dict[str, FactorScores],
    insider: dict[str, InsiderSignal],
    regime_scale: float = 1.0,
) -> dict[str, CombinedScore]:
    """Combine all signal sources into a single ranked score per stock.

    Weighting (rule-based mode):
    - Technical signals: 30% (short-term momentum/mean-reversion)
    - Factor scores: 40% (fundamental value - strongest alpha source)
    - Insider signals: 15% (strong but sparse)
    - Regime adjustment: 15% (macro overlay)

    Returns dict of ticker -> CombinedScore, ranked by combined_score.
    """
    cache_key = "combined_" + "_".join(sorted(technical.keys())) + f"_r{regime_scale}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    # Determine the set of tickers present in at least technical signals
    tickers = set(technical.keys())
    if not tickers:
        return {}

    # Step 1: Compute raw scores per ticker
    raw_scores: dict[str, dict] = {}

    for ticker in tickers:
        tech = technical.get(ticker)
        if tech is None:
            continue

        # Technical: normalize from [-10,10] to [0,1]
        tech_norm = _normalize_technical(tech.score)

        # Factor: normalize z-score to [0,1] via CDF
        factor_data = factors.get(ticker)
        if factor_data is not None:
            factor_norm = _normalize_factor(factor_data.composite_score)
        else:
            factor_norm = 0.5  # Neutral if no factor data

        # Insider: map signal to 0/0.5/1
        insider_data = insider.get(ticker)
        if insider_data is not None:
            insider_norm = _normalize_insider(insider_data.signal)
        else:
            insider_norm = 0.5  # Neutral if no insider data

        # Regime contribution: scale from 0.2-1.0 to 0-1
        # At regime_scale=1.0 (bull), regime contributes 1.0
        # At regime_scale=0.2 (crisis), regime contributes 0.2
        regime_norm = regime_scale

        raw_scores[ticker] = {
            "tech_norm": tech_norm,
            "factor_norm": factor_norm,
            "insider_norm": insider_norm,
            "regime_norm": regime_norm,
        }

    if not raw_scores:
        return {}

    # Step 2: Weighted combination
    combined_raw: dict[str, float] = {}
    for ticker, scores in raw_scores.items():
        combined = (
            WEIGHT_TECHNICAL * scores["tech_norm"]
            + WEIGHT_FACTOR * scores["factor_norm"]
            + WEIGHT_INSIDER * scores["insider_norm"]
            + WEIGHT_REGIME * scores["regime_norm"]
        )
        # Regime enters only as the weighted term above. Exposure scaling is
        # applied once, at order execution — multiplying here as well made a
        # crisis regime compound (0.2 in score × 0.2 on shares × ...).
        # Clamp to [0, 1]
        combined = max(0.0, min(1.0, combined))
        combined_raw[ticker] = combined

    # Step 3: Rank (highest score = rank 1)
    sorted_tickers = sorted(combined_raw.keys(), key=lambda t: combined_raw[t], reverse=True)

    # Step 4: Calculate suggested weights
    # Proportional to combined score, with max 20% per stock
    total_score = sum(combined_raw.values())
    suggested_weights: dict[str, float] = {}

    if total_score > 0:
        for ticker in sorted_tickers:
            raw_weight = combined_raw[ticker] / total_score
            suggested_weights[ticker] = min(raw_weight, MAX_POSITION_WEIGHT)

        # Renormalize after capping so weights sum to <= 1
        weight_sum = sum(suggested_weights.values())
        if weight_sum > 1.0:
            for ticker in suggested_weights:
                suggested_weights[ticker] /= weight_sum
    else:
        for ticker in sorted_tickers:
            suggested_weights[ticker] = 0.0

    # Step 5: Build CombinedScore objects
    results: dict[str, CombinedScore] = {}
    for rank_idx, ticker in enumerate(sorted_tickers, start=1):
        scores = raw_scores[ticker]
        combined = combined_raw[ticker]

        results[ticker] = CombinedScore(
            ticker=ticker,
            technical_score=round(scores["tech_norm"], 4),
            factor_score=round(scores["factor_norm"], 4),
            insider_score=round(scores["insider_norm"], 4),
            regime_scale=regime_scale,
            combined_score=round(combined, 4),
            rank=rank_idx,
            signal=_classify_combined(combined),
            confidence=round(_compute_confidence(combined), 4),
            suggested_weight=round(suggested_weights.get(ticker, 0.0), 4),
        )

    _set_cached(cache_key, results)
    return results


def format_combined_report(scores: dict[str, CombinedScore]) -> str:
    """Format combined scores for LLM prompt."""
    if not scores:
        return "No combined signal data available."

    sorted_scores = sorted(scores.values(), key=lambda s: s.combined_score, reverse=True)

    parts = ["COMBINED SIGNAL REPORT (ML Combiner)", "=" * 60, ""]

    # Summary table
    parts.append("RANKING (by combined score):")
    parts.append(
        f"  {'Rank':<5} {'Ticker':<8} {'Combined':>9} {'Signal':<12} "
        f"{'Conf':>5} {'Weight':>7}  {'Tech':>5} {'Factor':>7} {'Insider':>8}"
    )
    parts.append(
        f"  {'-'*5} {'-'*8} {'-'*9} {'-'*12} "
        f"{'-'*5} {'-'*7}  {'-'*5} {'-'*7} {'-'*8}"
    )

    for s in sorted_scores:
        parts.append(
            f"  {s.rank:<5d} {s.ticker:<8} {s.combined_score:>9.4f} {s.signal:<12} "
            f"{s.confidence:>5.2f} {s.suggested_weight:>6.1%}  "
            f"{s.technical_score:>5.2f} {s.factor_score:>7.4f} {s.insider_score:>8.1f}"
        )

    parts.append("")
    parts.append(f"  Regime scale: {sorted_scores[0].regime_scale:.0%}" if sorted_scores else "")

    # Top picks
    strong_buys = [s for s in sorted_scores if s.signal == "strong_buy"]
    if strong_buys:
        parts.append("")
        parts.append("STRONG BUY SIGNALS:")
        for s in strong_buys:
            parts.append(
                f"  {s.ticker}: combined={s.combined_score:.4f}, "
                f"confidence={s.confidence:.0%}, suggested weight={s.suggested_weight:.1%}"
            )

    # Sell signals
    sells = [s for s in sorted_scores if s.signal in ("sell", "strong_sell")]
    if sells:
        parts.append("")
        parts.append("SELL / STRONG SELL SIGNALS:")
        for s in sells:
            parts.append(
                f"  {s.ticker}: combined={s.combined_score:.4f}, "
                f"signal={s.signal.upper()}"
            )

    return "\n".join(parts)
