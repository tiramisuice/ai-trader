"""Tests for portfolio weight optimizer."""

from __future__ import annotations

import pytest

from api.quant.portfolio_optimizer import OptimalWeights, optimize_weights


# ===================================================================
# Basic functionality tests
# ===================================================================

class TestOptimizeWeightsBasic:
    def test_optimize_weights_basic(self):
        """Should produce valid weights for simple input."""
        tickers = ["AAPL", "MSFT", "GOOGL"]
        scores = {"AAPL": 0.8, "MSFT": 0.6, "GOOGL": 0.7}
        volatilities = {"AAPL": 0.02, "MSFT": 0.015, "GOOGL": 0.025}

        result = optimize_weights(tickers, scores, volatilities)

        assert isinstance(result, OptimalWeights)
        assert len(result.weights) == 3
        assert all(t in result.weights for t in tickers)
        assert all(w >= 0 for w in result.weights.values())
        assert result.cash_weight >= 0
        assert result.method == "score_weighted_inv_vol"

    def test_empty_tickers_returns_all_cash(self):
        """No tickers should return 100% cash."""
        result = optimize_weights([], {}, {})
        assert result.weights == {}
        assert result.cash_weight == 1.0

    def test_single_ticker(self):
        """Single ticker should get weight capped at max_position."""
        result = optimize_weights(
            tickers=["AAPL"],
            scores={"AAPL": 0.9},
            volatilities={"AAPL": 0.02},
            max_position=0.20,
        )
        assert "AAPL" in result.weights
        assert result.weights["AAPL"] <= 0.20 + 1e-6


# ===================================================================
# Constraint tests
# ===================================================================

class TestWeightsSumConstraint:
    def test_weights_sum_to_at_most_one(self):
        """Total weights + cash should equal ~1.0."""
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
        scores = {t: 0.7 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        result = optimize_weights(tickers, scores, volatilities)

        total = sum(result.weights.values()) + result.cash_weight
        assert abs(total - 1.0) < 0.01, f"Total allocation {total} != 1.0"

    def test_weights_never_exceed_one(self):
        """Sum of stock weights should never exceed 1.0."""
        tickers = [f"T{i}" for i in range(10)]
        scores = {t: 0.9 for t in tickers}
        volatilities = {t: 0.01 for t in tickers}

        result = optimize_weights(tickers, scores, volatilities)

        total_stock_weight = sum(result.weights.values())
        assert total_stock_weight <= 1.0 + 1e-6


class TestMaxPositionConstraint:
    def test_max_position_respected(self):
        """No single position should exceed max_position."""
        tickers = ["AAPL", "MSFT"]
        scores = {"AAPL": 0.99, "MSFT": 0.01}  # Very skewed
        volatilities = {"AAPL": 0.01, "MSFT": 0.05}  # AAPL low vol

        result = optimize_weights(
            tickers, scores, volatilities,
            max_position=0.15,
        )

        for t, w in result.weights.items():
            assert w <= 0.15 + 1e-6, f"{t} weight {w} exceeds max 0.15"

    def test_custom_max_position(self):
        """Custom max_position should be enforced."""
        result = optimize_weights(
            tickers=["ONLY"],
            scores={"ONLY": 0.9},
            volatilities={"ONLY": 0.02},
            max_position=0.10,
        )
        assert result.weights["ONLY"] <= 0.10 + 1e-6


class TestMinCashConstraint:
    def test_min_cash_maintained(self):
        """Cash weight should be at least min_cash."""
        tickers = [f"T{i}" for i in range(10)]
        scores = {t: 0.8 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        result = optimize_weights(
            tickers, scores, volatilities,
            min_cash=0.10,
        )

        assert result.cash_weight >= 0.10 - 1e-6, (
            f"Cash weight {result.cash_weight} < min_cash 0.10"
        )

    def test_default_min_cash(self):
        """Default min_cash (5%) should be maintained."""
        tickers = ["AAPL", "MSFT", "GOOGL"]
        scores = {t: 0.7 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        result = optimize_weights(tickers, scores, volatilities)

        assert result.cash_weight >= 0.05 - 1e-6


# ===================================================================
# Regime scaling tests
# ===================================================================

class TestRegimeReducesInvestment:
    def test_bear_regime_less_invested(self):
        """Bear regime (scale=0.5) should result in less total investment."""
        tickers = ["AAPL", "MSFT", "GOOGL"]
        scores = {t: 0.7 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        bull = optimize_weights(tickers, scores, volatilities, regime_scale=1.0)
        bear = optimize_weights(tickers, scores, volatilities, regime_scale=0.5)

        bull_invested = sum(bull.weights.values())
        bear_invested = sum(bear.weights.values())

        assert bear_invested < bull_invested, (
            f"Bear invested {bear_invested} should be < bull invested {bull_invested}"
        )

    def test_crisis_regime_minimal_investment(self):
        """Crisis regime (scale=0.2) should result in very little investment."""
        tickers = ["AAPL", "MSFT"]
        scores = {t: 0.7 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        crisis = optimize_weights(tickers, scores, volatilities, regime_scale=0.2)

        crisis_invested = sum(crisis.weights.values())
        # At regime 0.2, target allocation = (1-0.05)*0.2 = 0.19
        assert crisis_invested <= 0.20 + 1e-6

    def test_regime_scale_1_full_allocation(self):
        """Bull regime (scale=1.0) should use close to full allocation."""
        tickers = ["AAPL", "MSFT", "GOOGL"]
        scores = {t: 0.7 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        bull = optimize_weights(tickers, scores, volatilities, regime_scale=1.0)

        bull_invested = sum(bull.weights.values())
        # Target allocation = (1-0.05)*1.0 = 0.95
        assert bull_invested > 0.5, (
            f"Bull invested {bull_invested} should be substantial"
        )


# ===================================================================
# Inverse volatility behavior tests
# ===================================================================

class TestInverseVolFavorsLowVol:
    def test_low_vol_gets_higher_weight(self):
        """Lower volatility stock should get higher weight, all else equal."""
        tickers = ["LOW_VOL", "HIGH_VOL"]
        scores = {"LOW_VOL": 0.7, "HIGH_VOL": 0.7}  # Same score
        volatilities = {"LOW_VOL": 0.01, "HIGH_VOL": 0.05}  # 5x vol difference

        # Use high max_position to avoid capping both at the same level
        result = optimize_weights(
            tickers, scores, volatilities,
            max_position=0.80,
        )

        assert result.weights["LOW_VOL"] > result.weights["HIGH_VOL"], (
            f"LOW_VOL weight {result.weights['LOW_VOL']} should be > "
            f"HIGH_VOL weight {result.weights['HIGH_VOL']}"
        )

    def test_extreme_vol_difference(self):
        """Very high volatility stock should get much less weight."""
        tickers = ["SAFE", "WILD"]
        scores = {"SAFE": 0.6, "WILD": 0.6}
        volatilities = {"SAFE": 0.005, "WILD": 0.10}  # 20x difference

        # Use high max_position to avoid capping both at the same level
        result = optimize_weights(
            tickers, scores, volatilities,
            max_position=0.80,
        )

        # SAFE should get significantly more weight
        assert result.weights["SAFE"] > result.weights["WILD"] * 2


# ===================================================================
# Score influence tests
# ===================================================================

class TestScoreInfluence:
    def test_higher_score_gets_more_weight(self):
        """Higher combined score should increase weight, given same volatility."""
        tickers = ["GOOD", "BAD"]
        scores = {"GOOD": 0.9, "BAD": 0.2}
        volatilities = {"GOOD": 0.02, "BAD": 0.02}  # Same vol

        # Use high max_position to avoid capping both at the same level
        result = optimize_weights(
            tickers, scores, volatilities,
            max_position=0.80,
        )

        assert result.weights["GOOD"] > result.weights["BAD"], (
            f"GOOD weight {result.weights['GOOD']} should be > "
            f"BAD weight {result.weights['BAD']}"
        )

    def test_zero_scores_handled(self):
        """All-zero scores should not crash."""
        tickers = ["A", "B"]
        scores = {"A": 0.0, "B": 0.0}
        volatilities = {"A": 0.02, "B": 0.02}

        result = optimize_weights(tickers, scores, volatilities)

        assert isinstance(result, OptimalWeights)
        # With zero scores, should get equal weights or zero
        total = sum(result.weights.values())
        assert total >= 0


# ===================================================================
# Edge case tests
# ===================================================================

class TestEdgeCases:
    def test_missing_volatility_triggers_fallback(self):
        """Missing volatility for some tickers should use available data."""
        tickers = ["HAS_VOL", "NO_VOL"]
        scores = {"HAS_VOL": 0.7, "NO_VOL": 0.7}
        volatilities = {"HAS_VOL": 0.02}  # NO_VOL missing

        result = optimize_weights(tickers, scores, volatilities)

        # Should still produce weights (at least for HAS_VOL)
        assert "HAS_VOL" in result.weights

    def test_zero_volatility_excluded(self):
        """Ticker with zero volatility should be excluded from inv-vol method."""
        tickers = ["NORMAL", "ZERO_VOL"]
        scores = {"NORMAL": 0.7, "ZERO_VOL": 0.7}
        volatilities = {"NORMAL": 0.02, "ZERO_VOL": 0.0}

        result = optimize_weights(tickers, scores, volatilities)

        # ZERO_VOL should not appear in score_weighted_inv_vol method
        if result.method == "score_weighted_inv_vol":
            assert "ZERO_VOL" not in result.weights or result.weights.get("ZERO_VOL", 0) == 0

    def test_all_missing_data_returns_cash(self):
        """If no valid data, return all cash."""
        result = optimize_weights(
            tickers=["A", "B"],
            scores={},
            volatilities={},
        )
        assert result.cash_weight == 1.0

    def test_many_tickers_capped_properly(self):
        """With many tickers, all should be capped and sum properly."""
        tickers = [f"T{i}" for i in range(20)]
        scores = {t: 0.7 for t in tickers}
        volatilities = {t: 0.02 for t in tickers}

        result = optimize_weights(
            tickers, scores, volatilities,
            max_position=0.10,
        )

        for t, w in result.weights.items():
            assert w <= 0.10 + 1e-6

        total = sum(result.weights.values()) + result.cash_weight
        assert abs(total - 1.0) < 0.05
