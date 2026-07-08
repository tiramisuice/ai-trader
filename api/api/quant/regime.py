"""Market regime detection — HMM-based with rule-based fallback."""

from __future__ import annotations
import logging
import time
import numpy as np
from dataclasses import dataclass

from api.data.fetch import fetch_history

logger = logging.getLogger(__name__)

# Simple dict cache: {cache_key: (timestamp, data)}
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 300  # 5 minutes (regime changes slowly)


def _get_cached(key: str):
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data: object):
    _cache[key] = (time.time(), data)


@dataclass
class RegimeState:
    """Current market regime and position scaling."""
    current_regime: str  # "bull", "bear", "crisis"
    regime_probabilities: dict[str, float]  # {"bull": 0.7, "bear": 0.2, "crisis": 0.1}
    position_scale: float  # 0.0 to 1.0 — multiply all positions by this
    regime_description: str


# Regime -> position scale mapping
_REGIME_SCALE = {
    "bull": 1.0,
    "bear": 0.5,
    "crisis": 0.2,
}


def _fetch_market_data(lookback_days: int = 252) -> tuple[np.ndarray, np.ndarray, float, float | None] | None:
    """Fetch SPY returns + VIX for regime detection.

    Returns (daily_returns, rolling_vol_20d, sma_200, current_vix) or None.
    """
    try:
        # Fetch a bit more data than needed for SMA200
        hist = fetch_history("SPY", "2y")
        if hist.empty or len(hist) < lookback_days:
            logger.warning("Insufficient SPY data (%d rows)", len(hist))
            return None

        close = hist["Close"].values
        price = float(close[-1])

        # Daily returns
        returns = np.diff(close) / close[:-1]
        returns = returns[-lookback_days:]

        # 20-day rolling volatility
        if len(returns) >= 20:
            rolling_vol = np.array([
                np.std(returns[max(0, i - 19):i + 1])
                for i in range(len(returns))
            ])
        else:
            rolling_vol = np.full(len(returns), np.std(returns))

        # SMA 200
        if len(close) >= 200:
            sma_200 = float(np.mean(close[-200:]))
        else:
            sma_200 = float(np.mean(close))

        # VIX
        current_vix = None
        try:
            vix_hist = fetch_history("^VIX", "5d")
            if not vix_hist.empty:
                current_vix = float(vix_hist["Close"].iloc[-1])
        except Exception:
            pass

        return returns, rolling_vol, sma_200, current_vix
    except Exception as e:
        logger.error("Failed to fetch market data: %s", e)
        return None


def _detect_regime_hmm(returns: np.ndarray, rolling_vol: np.ndarray) -> RegimeState | None:
    """Detect regime using Gaussian HMM (3 states)."""
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        logger.info("hmmlearn not installed, falling back to rule-based regime detection")
        return None

    try:
        # Features: daily returns + rolling volatility
        features = np.column_stack([returns, rolling_vol])

        model = GaussianHMM(
            n_components=3,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        model.fit(features)

        # Get state probabilities for the last observation
        _, posteriors = model.score_samples(features)
        last_probs = posteriors[-1]  # Probabilities for each state

        # Identify states by their mean return
        state_means = model.means_[:, 0]  # Mean of the returns feature
        state_vols = model.means_[:, 1]  # Mean of the volatility feature

        # Sort states by mean return: crisis (lowest), bear, bull (highest)
        state_order = np.argsort(state_means)
        crisis_idx, bear_idx, bull_idx = state_order[0], state_order[1], state_order[2]

        probs = {
            "bull": float(last_probs[bull_idx]),
            "bear": float(last_probs[bear_idx]),
            "crisis": float(last_probs[crisis_idx]),
        }

        # Current regime = highest probability
        current_regime = max(probs, key=probs.get)
        position_scale = _REGIME_SCALE[current_regime]

        # Build description
        bull_ret = float(state_means[bull_idx]) * 252  # Annualized
        bear_ret = float(state_means[bear_idx]) * 252
        crisis_ret = float(state_means[crisis_idx]) * 252

        description = (
            f"HMM regime: {current_regime.upper()} "
            f"(bull={probs['bull']:.0%}, bear={probs['bear']:.0%}, crisis={probs['crisis']:.0%}). "
            f"State returns (ann.): bull={bull_ret:+.1%}, bear={bear_ret:+.1%}, crisis={crisis_ret:+.1%}. "
            f"Position scale: {position_scale:.0%}."
        )

        return RegimeState(
            current_regime=current_regime,
            regime_probabilities=probs,
            position_scale=position_scale,
            regime_description=description,
        )
    except Exception as e:
        logger.warning("HMM fit failed: %s, falling back to rule-based", e)
        return None


def _detect_regime_rules(
    spy_price: float | None = None,
    sma_200: float | None = None,
    vix: float | None = None,
) -> RegimeState:
    """Rule-based fallback regime detection.

    - If SPY > 200-day SMA and VIX < 20 -> Bull
    - If SPY < 200-day SMA or VIX > 30 -> Bear
    - If VIX > 40 -> Crisis
    """
    # Default to neutral if no data
    if spy_price is None or sma_200 is None:
        return RegimeState(
            current_regime="bull",
            regime_probabilities={"bull": 0.5, "bear": 0.3, "crisis": 0.2},
            position_scale=1.0,
            regime_description="Insufficient data for regime detection. Defaulting to bull (full position).",
        )

    above_sma = spy_price > sma_200
    vix_val = vix if vix is not None else 20.0  # Default moderate VIX

    if vix_val > 40:
        regime = "crisis"
        probs = {"bull": 0.05, "bear": 0.25, "crisis": 0.70}
        desc = f"CRISIS: VIX={vix_val:.1f} (>40). Extreme fear. Minimal positions."
    elif not above_sma or vix_val > 30:
        regime = "bear"
        reasons = []
        if not above_sma:
            reasons.append(f"SPY below 200-SMA (${spy_price:.2f} < ${sma_200:.2f})")
        if vix_val > 30:
            reasons.append(f"VIX elevated ({vix_val:.1f} > 30)")
        probs = {"bull": 0.15, "bear": 0.65, "crisis": 0.20}
        desc = f"BEAR: {'; '.join(reasons)}. Half positions."
    elif above_sma and vix_val < 20:
        regime = "bull"
        probs = {"bull": 0.75, "bear": 0.20, "crisis": 0.05}
        desc = f"BULL: SPY above 200-SMA (${spy_price:.2f} > ${sma_200:.2f}), VIX low ({vix_val:.1f}). Full positions."
    else:
        # Above SMA but VIX between 20-30 -> cautious bull
        regime = "bull"
        probs = {"bull": 0.55, "bear": 0.35, "crisis": 0.10}
        desc = f"BULL (cautious): SPY above 200-SMA but VIX moderate ({vix_val:.1f}). Full positions with caution."

    position_scale = _REGIME_SCALE[regime]

    return RegimeState(
        current_regime=regime,
        regime_probabilities=probs,
        position_scale=position_scale,
        regime_description=desc,
    )


def detect_regime(lookback_days: int = 252) -> RegimeState:
    """Detect current market regime using HMM on SPY returns.

    Falls back to rule-based detection if hmmlearn is unavailable or HMM fails.
    """
    cache_key = f"regime_{lookback_days}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    market_data = _fetch_market_data(lookback_days)
    if market_data is None:
        result = _detect_regime_rules()
        _set_cached(cache_key, result)
        return result

    returns, rolling_vol, sma_200, vix = market_data
    spy_price = None
    try:
        spy_hist = fetch_history("SPY", "5d")
        if not spy_hist.empty:
            spy_price = float(spy_hist["Close"].iloc[-1])
    except Exception:
        pass

    # Try HMM first
    result = _detect_regime_hmm(returns, rolling_vol)
    if result is not None:
        _set_cached(cache_key, result)
        return result

    # Fallback to rules
    result = _detect_regime_rules(spy_price=spy_price, sma_200=sma_200, vix=vix)
    _set_cached(cache_key, result)
    return result
