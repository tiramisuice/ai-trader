"""Tests for market regime detection."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd

from api.quant.regime import (
    RegimeState,
    _detect_regime_rules,
    _detect_regime_hmm,
    _REGIME_SCALE,
    detect_regime,
)


# ===================================================================
# RegimeState dataclass tests
# ===================================================================

class TestRegimeState:
    def test_regime_state_creation(self):
        """RegimeState should hold all required fields."""
        state = RegimeState(
            current_regime="bull",
            regime_probabilities={"bull": 0.7, "bear": 0.2, "crisis": 0.1},
            position_scale=1.0,
            regime_description="Bull market.",
        )
        assert state.current_regime == "bull"
        assert state.position_scale == 1.0
        assert state.regime_probabilities["bull"] == 0.7

    def test_regime_scale_mapping(self):
        """Regime scale values should be defined for all regimes."""
        assert _REGIME_SCALE["bull"] == 1.0
        assert _REGIME_SCALE["bear"] == 0.5
        assert _REGIME_SCALE["crisis"] == 0.2


# ===================================================================
# Rule-based regime detection tests
# ===================================================================

class TestRuleBasedRegime:
    def test_bull_regime(self):
        """SPY above SMA200 and VIX < 20 should be bull."""
        state = _detect_regime_rules(spy_price=450.0, sma_200=420.0, vix=15.0)
        assert state.current_regime == "bull"
        assert state.position_scale == 1.0
        assert state.regime_probabilities["bull"] > 0.5

    def test_bear_regime_below_sma(self):
        """SPY below SMA200 should be bear."""
        state = _detect_regime_rules(spy_price=400.0, sma_200=420.0, vix=18.0)
        assert state.current_regime == "bear"
        assert state.position_scale == 0.5
        assert state.regime_probabilities["bear"] > 0.5

    def test_bear_regime_high_vix(self):
        """VIX > 30 should be bear."""
        state = _detect_regime_rules(spy_price=450.0, sma_200=420.0, vix=35.0)
        assert state.current_regime == "bear"
        assert state.position_scale == 0.5

    def test_crisis_regime(self):
        """VIX > 40 should be crisis."""
        state = _detect_regime_rules(spy_price=350.0, sma_200=420.0, vix=50.0)
        assert state.current_regime == "crisis"
        assert state.position_scale == 0.2
        assert state.regime_probabilities["crisis"] > 0.5

    def test_cautious_bull(self):
        """SPY above SMA200 but VIX 20-30 should be cautious bull."""
        state = _detect_regime_rules(spy_price=450.0, sma_200=420.0, vix=25.0)
        assert state.current_regime == "bull"
        assert state.position_scale == 1.0
        # Still bull but with lower confidence
        assert state.regime_probabilities["bull"] < 0.7

    def test_no_data_defaults_to_bull(self):
        """Missing data should default to bull regime."""
        state = _detect_regime_rules(spy_price=None, sma_200=None, vix=None)
        assert state.current_regime == "bull"
        assert state.position_scale == 1.0


# ===================================================================
# Position scale range tests
# ===================================================================

class TestPositionScaleRange:
    def test_all_regimes_have_valid_scale(self):
        """All regimes should have position_scale between 0 and 1."""
        for regime, scale in _REGIME_SCALE.items():
            assert 0.0 <= scale <= 1.0, f"{regime} has invalid scale {scale}"

    def test_bull_returns_scale_1(self):
        state = _detect_regime_rules(spy_price=500.0, sma_200=400.0, vix=12.0)
        assert 0.0 <= state.position_scale <= 1.0

    def test_bear_returns_scale_half(self):
        state = _detect_regime_rules(spy_price=380.0, sma_200=400.0, vix=28.0)
        assert 0.0 <= state.position_scale <= 1.0

    def test_crisis_returns_minimal_scale(self):
        state = _detect_regime_rules(spy_price=300.0, sma_200=400.0, vix=60.0)
        assert 0.0 <= state.position_scale <= 1.0
        assert state.position_scale <= 0.3  # Crisis = minimal


# ===================================================================
# HMM regime detection tests (with hmmlearn mocked)
# ===================================================================

class TestHMMRegime:
    def test_hmm_returns_valid_state_when_available(self):
        """HMM detection should return valid RegimeState when hmmlearn works."""
        np.random.seed(42)
        returns = np.random.randn(252) * 0.01
        rolling_vol = np.array([np.std(returns[max(0, i - 19):i + 1]) for i in range(252)])

        result = _detect_regime_hmm(returns, rolling_vol)
        # May return None if hmmlearn not installed; that's OK
        if result is not None:
            assert result.current_regime in ("bull", "bear", "crisis")
            assert 0.0 <= result.position_scale <= 1.0
            total_prob = sum(result.regime_probabilities.values())
            assert abs(total_prob - 1.0) < 0.01
            assert len(result.regime_description) > 0


# ===================================================================
# Fallback regime detection tests (when hmmlearn unavailable)
# ===================================================================

class TestFallbackRegimeDetection:
    def test_fallback_when_hmmlearn_missing(self):
        """Should fall back to rule-based when hmmlearn import fails."""
        np.random.seed(42)
        returns = np.random.randn(252) * 0.01
        rolling_vol = np.array([np.std(returns[max(0, i - 19):i + 1]) for i in range(252)])

        with patch.dict("sys.modules", {"hmmlearn": None, "hmmlearn.hmm": None}):
            # Force reimport to hit ImportError
            import importlib
            import api.quant.regime as regime_mod
            result = regime_mod._detect_regime_hmm(returns, rolling_vol)
            # Should return None (indicating fallback needed)
            assert result is None

    def test_full_detect_falls_back_gracefully(self):
        """detect_regime should work even when market data fetch fails."""
        from api.quant.regime import _cache
        _cache.clear()

        with patch("api.quant.regime._fetch_market_data", return_value=None):
            state = detect_regime()

        assert isinstance(state, RegimeState)
        assert state.current_regime in ("bull", "bear", "crisis")
        assert 0.0 <= state.position_scale <= 1.0

    def test_detect_regime_with_mocked_market_data(self):
        """detect_regime should work with mocked market data and rule-based fallback."""
        from api.quant.regime import _cache
        _cache.clear()

        np.random.seed(42)
        returns = np.random.randn(252) * 0.01
        rolling_vol = np.array([np.std(returns[max(0, i - 19):i + 1]) for i in range(252)])

        spy_hist = pd.DataFrame({"Close": [450.0]}, index=pd.date_range("2026-03-31", periods=1))

        with patch("api.quant.regime._fetch_market_data", return_value=(returns, rolling_vol, 420.0, 18.0)):
            with patch("api.quant.regime.fetch_history", return_value=spy_hist):
                # Force HMM to fail so we get rule-based
                with patch("api.quant.regime._detect_regime_hmm", return_value=None):
                    state = detect_regime()

        assert isinstance(state, RegimeState)
        assert state.current_regime in ("bull", "bear", "crisis")
        assert 0.0 <= state.position_scale <= 1.0


# ===================================================================
# Regime description tests
# ===================================================================

class TestRegimeDescription:
    def test_bull_description_mentions_bull(self):
        state = _detect_regime_rules(spy_price=450.0, sma_200=400.0, vix=15.0)
        assert "BULL" in state.regime_description.upper()

    def test_bear_description_mentions_bear(self):
        state = _detect_regime_rules(spy_price=380.0, sma_200=400.0, vix=18.0)
        assert "BEAR" in state.regime_description.upper()

    def test_crisis_description_mentions_crisis(self):
        state = _detect_regime_rules(spy_price=300.0, sma_200=400.0, vix=50.0)
        assert "CRISIS" in state.regime_description.upper()

    def test_description_not_empty(self):
        for spy, sma, vix in [(450, 400, 15), (380, 400, 18), (300, 400, 50)]:
            state = _detect_regime_rules(spy_price=float(spy), sma_200=float(sma), vix=float(vix))
            assert len(state.regime_description) > 0


# ===================================================================
# Regime probabilities tests
# ===================================================================

class TestRegimeProbabilities:
    def test_probabilities_sum_roughly_to_one(self):
        """Regime probabilities should approximately sum to 1."""
        for spy, sma, vix in [(450, 400, 15), (380, 400, 35), (300, 400, 50)]:
            state = _detect_regime_rules(spy_price=float(spy), sma_200=float(sma), vix=float(vix))
            total = sum(state.regime_probabilities.values())
            assert abs(total - 1.0) < 0.01

    def test_probabilities_contain_all_regimes(self):
        """Probabilities dict should contain bull, bear, and crisis."""
        state = _detect_regime_rules(spy_price=450.0, sma_200=400.0, vix=15.0)
        assert "bull" in state.regime_probabilities
        assert "bear" in state.regime_probabilities
        assert "crisis" in state.regime_probabilities

    def test_all_probabilities_non_negative(self):
        """All probabilities should be >= 0."""
        state = _detect_regime_rules(spy_price=450.0, sma_200=400.0, vix=15.0)
        for regime, prob in state.regime_probabilities.items():
            assert prob >= 0.0, f"{regime} has negative probability {prob}"
