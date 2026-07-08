"""Portfolio weight optimizer — risk parity and inverse volatility."""

from __future__ import annotations

import logging
import numpy as np
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OptimalWeights:
    """Optimal portfolio weights output."""
    weights: dict[str, float]  # ticker -> weight (0-1, sums to <=1)
    cash_weight: float         # Remaining cash portion
    method: str                # "score_weighted_inv_vol", "equal_weight"


def optimize_weights(
    tickers: list[str],
    scores: dict[str, float],       # ticker -> combined score (0-1)
    volatilities: dict[str, float], # ticker -> daily vol
    max_position: float = 0.20,
    min_cash: float = 0.05,
    regime_scale: float = 1.0,
) -> OptimalWeights:
    """Calculate optimal portfolio weights.

    Method: Score-weighted inverse volatility
    - Start with inverse-vol weights (lower vol = higher weight)
    - Scale by combined score (higher score = more weight)
    - Apply max position and min cash constraints
    - Scale by regime (bear market = less invested)

    Parameters
    ----------
    tickers : list of tickers to allocate
    scores : combined score per ticker (0-1 from ml_combiner)
    volatilities : daily volatility per ticker
    max_position : max weight per single stock (default 20%)
    min_cash : minimum cash to keep (default 5%)
    regime_scale : 0.2-1.0 from regime detector
    """
    if not tickers:
        return OptimalWeights(weights={}, cash_weight=1.0, method="score_weighted_inv_vol")

    # Filter to tickers that have both scores and volatilities
    valid_tickers = [
        t for t in tickers
        if t in scores and t in volatilities and volatilities[t] > 0
    ]

    if not valid_tickers:
        # Fallback: equal weight for tickers with scores
        scored_tickers = [t for t in tickers if t in scores and scores[t] > 0]
        if not scored_tickers:
            return OptimalWeights(weights={}, cash_weight=1.0, method="equal_weight")

        investable = (1.0 - min_cash) * regime_scale
        equal_w = investable / len(scored_tickers)
        equal_w = min(equal_w, max_position)

        weights = {t: round(equal_w, 4) for t in scored_tickers}
        total_invested = sum(weights.values())
        cash_weight = round(1.0 - total_invested, 4)

        return OptimalWeights(
            weights=weights,
            cash_weight=cash_weight,
            method="equal_weight",
        )

    # Step 1: Inverse volatility weights
    inv_vols = {t: 1.0 / volatilities[t] for t in valid_tickers}
    inv_vol_sum = sum(inv_vols.values())
    inv_vol_weights = {t: inv_vols[t] / inv_vol_sum for t in valid_tickers}

    # Step 2: Score weights
    score_values = {t: scores[t] for t in valid_tickers}
    score_sum = sum(score_values.values())

    if score_sum > 0:
        score_weights = {t: score_values[t] / score_sum for t in valid_tickers}
    else:
        # All scores are 0 — use equal score weight
        score_weights = {t: 1.0 / len(valid_tickers) for t in valid_tickers}

    # Step 3: Combine inverse-vol and score weights
    combined = {t: inv_vol_weights[t] * score_weights[t] for t in valid_tickers}
    combined_sum = sum(combined.values())

    if combined_sum > 0:
        # Normalize to target allocation = (1 - min_cash) * regime_scale
        target_allocation = (1.0 - min_cash) * regime_scale
        weights = {t: (combined[t] / combined_sum) * target_allocation for t in valid_tickers}
    else:
        weights = {t: 0.0 for t in valid_tickers}

    # Step 4: Cap each position at max_position
    capped = False
    for t in list(weights.keys()):
        if weights[t] > max_position:
            weights[t] = max_position
            capped = True

    # Step 5: Renormalize after capping
    # Only the uncapped positions need renormalization
    if capped:
        capped_total = sum(w for w in weights.values() if w >= max_position)
        uncapped_tickers = [t for t in weights if weights[t] < max_position]
        uncapped_total = sum(weights[t] for t in uncapped_tickers)

        remaining_allocation = target_allocation - capped_total

        if remaining_allocation > 0 and uncapped_total > 0:
            for t in uncapped_tickers:
                weights[t] = (weights[t] / uncapped_total) * remaining_allocation
                # Re-cap after redistribution
                weights[t] = min(weights[t], max_position)
        elif remaining_allocation <= 0:
            for t in uncapped_tickers:
                weights[t] = 0.0

    # Round final weights
    weights = {t: round(w, 4) for t, w in weights.items()}

    # Calculate cash weight
    total_invested = sum(weights.values())
    cash_weight = round(max(min_cash, 1.0 - total_invested), 4)

    return OptimalWeights(
        weights=weights,
        cash_weight=cash_weight,
        method="score_weighted_inv_vol",
    )
