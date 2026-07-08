"""Tests for ML signal combiner."""

from __future__ import annotations

import pytest

from api.quant.signals import TechnicalSignals
from api.quant.factors import FactorScores
from api.quant.insider import InsiderSignal
from api.quant.ml_combiner import (
    CombinedScore,
    combine_signals,
    format_combined_report,
    _normalize_technical,
    _normalize_factor,
    _normalize_insider,
    _classify_combined,
    _compute_confidence,
    WEIGHT_TECHNICAL,
    WEIGHT_FACTOR,
    WEIGHT_INSIDER,
    WEIGHT_REGIME,
    MAX_POSITION_WEIGHT,
)


# ---------------------------------------------------------------------------
# Helpers: build test data with sensible defaults
# ---------------------------------------------------------------------------

def make_signal(**overrides) -> TechnicalSignals:
    """Create a TechnicalSignals with defaults."""
    defaults = dict(
        ticker="TEST",
        price=100.0,
        sma_20=98.0,
        sma_50=95.0,
        sma_200=90.0,
        price_vs_sma20="above",
        price_vs_sma50="above",
        price_vs_sma200="above",
        golden_cross=False,
        death_cross=False,
        rsi_14=50.0,
        rsi_signal="neutral",
        macd=0.5,
        macd_signal=0.3,
        macd_histogram=0.2,
        macd_crossover="neutral",
        bb_upper=110.0,
        bb_lower=90.0,
        bb_position="inside",
        volume=1_000_000,
        avg_volume_20=800_000.0,
        volume_ratio=1.25,
        high_volume=False,
        atr_14=2.5,
        daily_volatility=0.015,
        score=0,
        signal="neutral",
    )
    defaults.update(overrides)
    return TechnicalSignals(**defaults)


def make_factor_scores(**overrides) -> FactorScores:
    """Create a FactorScores with defaults."""
    defaults = dict(
        ticker="TEST",
        value_score=0.0,
        momentum_score=0.0,
        quality_score=0.0,
        size_score=0.0,
        volatility_score=0.0,
        composite_score=0.0,
        factor_signal="neutral",
        earnings_yield=0.05,
        book_to_market=0.5,
        roe=0.15,
        profit_margin=0.10,
        debt_to_equity=0.5,
        market_cap=100e9,
        momentum_12_1=0.10,
        momentum_6_1=0.05,
        volatility_60d=0.20,
    )
    defaults.update(overrides)
    return FactorScores(**defaults)


def make_insider(**overrides) -> InsiderSignal:
    """Create an InsiderSignal with defaults."""
    defaults = dict(
        ticker="TEST",
        net_insider_buys_30d=0,
        signal="neutral",
        details=[],
    )
    defaults.update(overrides)
    return InsiderSignal(**defaults)


# ===================================================================
# Normalization function tests
# ===================================================================

class TestNormalizeTechnical:
    def test_min_score(self):
        assert _normalize_technical(-10) == 0.0

    def test_max_score(self):
        assert _normalize_technical(10) == 1.0

    def test_zero_score(self):
        assert _normalize_technical(0) == 0.5

    def test_positive_score(self):
        result = _normalize_technical(5)
        assert 0.5 < result < 1.0
        assert abs(result - 0.75) < 1e-10


class TestNormalizeFactor:
    def test_zero_zscore_is_half(self):
        result = _normalize_factor(0.0)
        assert abs(result - 0.5) < 1e-6

    def test_positive_zscore_above_half(self):
        result = _normalize_factor(1.0)
        assert result > 0.5

    def test_negative_zscore_below_half(self):
        result = _normalize_factor(-1.0)
        assert result < 0.5

    def test_extreme_positive(self):
        result = _normalize_factor(3.0)
        assert result > 0.99

    def test_extreme_negative(self):
        result = _normalize_factor(-3.0)
        assert result < 0.01


class TestNormalizeInsider:
    def test_bullish(self):
        assert _normalize_insider("bullish") == 1.0

    def test_neutral(self):
        assert _normalize_insider("neutral") == 0.5

    def test_bearish(self):
        assert _normalize_insider("bearish") == 0.0

    def test_unknown_defaults_neutral(self):
        assert _normalize_insider("unknown") == 0.5


# ===================================================================
# Classification tests
# ===================================================================

class TestClassifyCombined:
    def test_strong_buy(self):
        assert _classify_combined(0.80) == "strong_buy"
        assert _classify_combined(0.75) == "strong_buy"
        assert _classify_combined(1.0) == "strong_buy"

    def test_buy(self):
        assert _classify_combined(0.60) == "buy"
        assert _classify_combined(0.70) == "buy"

    def test_neutral(self):
        assert _classify_combined(0.50) == "neutral"
        assert _classify_combined(0.41) == "neutral"
        assert _classify_combined(0.59) == "neutral"

    def test_sell(self):
        assert _classify_combined(0.40) == "sell"
        assert _classify_combined(0.30) == "sell"

    def test_strong_sell(self):
        assert _classify_combined(0.25) == "strong_sell"
        assert _classify_combined(0.10) == "strong_sell"
        assert _classify_combined(0.0) == "strong_sell"


# ===================================================================
# Confidence tests
# ===================================================================

class TestConfidence:
    def test_neutral_zero_confidence(self):
        assert _compute_confidence(0.5) == 0.0

    def test_extreme_high_confidence(self):
        assert _compute_confidence(1.0) == 1.0

    def test_extreme_low_confidence(self):
        assert _compute_confidence(0.0) == 1.0

    def test_mid_confidence(self):
        conf = _compute_confidence(0.75)
        assert abs(conf - 0.5) < 1e-10


# ===================================================================
# combine_signals integration tests
# ===================================================================

class TestCombineSignals:
    def setup_method(self):
        """Clear cache before each test."""
        from api.quant.ml_combiner import _cache
        _cache.clear()

    def test_combine_signals_basic(self):
        """Should combine signals for multiple stocks."""
        technical = {
            "AAPL": make_signal(ticker="AAPL", score=5),
            "MSFT": make_signal(ticker="MSFT", score=-3),
            "TSLA": make_signal(ticker="TSLA", score=0),
        }
        factors = {
            "AAPL": make_factor_scores(ticker="AAPL", composite_score=1.0),
            "MSFT": make_factor_scores(ticker="MSFT", composite_score=-0.5),
            "TSLA": make_factor_scores(ticker="TSLA", composite_score=0.0),
        }
        insider = {
            "AAPL": make_insider(ticker="AAPL", signal="bullish"),
            "MSFT": make_insider(ticker="MSFT", signal="bearish"),
            "TSLA": make_insider(ticker="TSLA", signal="neutral"),
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)

        assert len(result) == 3
        assert "AAPL" in result
        assert "MSFT" in result
        assert "TSLA" in result

        # AAPL should rank highest (bullish everything)
        assert result["AAPL"].rank == 1
        assert result["AAPL"].combined_score > result["MSFT"].combined_score
        assert result["AAPL"].combined_score > result["TSLA"].combined_score

    def test_combined_score_range(self):
        """All combined scores should be in [0, 1]."""
        technical = {
            "A": make_signal(ticker="A", score=10),
            "B": make_signal(ticker="B", score=-10),
            "C": make_signal(ticker="C", score=0),
        }
        factors = {
            "A": make_factor_scores(ticker="A", composite_score=3.0),
            "B": make_factor_scores(ticker="B", composite_score=-3.0),
            "C": make_factor_scores(ticker="C", composite_score=0.0),
        }
        insider = {
            "A": make_insider(ticker="A", signal="bullish"),
            "B": make_insider(ticker="B", signal="bearish"),
            "C": make_insider(ticker="C", signal="neutral"),
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)

        for ticker, score in result.items():
            assert 0.0 <= score.combined_score <= 1.0, (
                f"{ticker} has combined_score={score.combined_score} outside [0,1]"
            )

    def test_ranking_order(self):
        """Highest combined score should get rank 1."""
        technical = {
            "HIGH": make_signal(ticker="HIGH", score=8),
            "MID": make_signal(ticker="MID", score=0),
            "LOW": make_signal(ticker="LOW", score=-8),
        }
        factors = {
            "HIGH": make_factor_scores(ticker="HIGH", composite_score=2.0),
            "MID": make_factor_scores(ticker="MID", composite_score=0.0),
            "LOW": make_factor_scores(ticker="LOW", composite_score=-2.0),
        }
        insider = {
            "HIGH": make_insider(ticker="HIGH", signal="bullish"),
            "MID": make_insider(ticker="MID", signal="neutral"),
            "LOW": make_insider(ticker="LOW", signal="bearish"),
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)

        assert result["HIGH"].rank == 1
        assert result["MID"].rank == 2
        assert result["LOW"].rank == 3

    def test_signal_classification(self):
        """Combined signal labels should match score thresholds."""
        technical = {
            "BULL": make_signal(ticker="BULL", score=10),
            "BEAR": make_signal(ticker="BEAR", score=-10),
        }
        factors = {
            "BULL": make_factor_scores(ticker="BULL", composite_score=3.0),
            "BEAR": make_factor_scores(ticker="BEAR", composite_score=-3.0),
        }
        insider = {
            "BULL": make_insider(ticker="BULL", signal="bullish"),
            "BEAR": make_insider(ticker="BEAR", signal="bearish"),
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)

        # Extremely bullish stock should be strong_buy or buy
        assert result["BULL"].signal in ("strong_buy", "buy")
        # Extremely bearish stock should be sell or strong_sell
        assert result["BEAR"].signal in ("sell", "strong_sell")

    def test_suggested_weights_sum_to_less_than_1(self):
        """Suggested weights should sum to at most 1.0."""
        technical = {
            f"T{i}": make_signal(ticker=f"T{i}", score=i)
            for i in range(1, 8)
        }
        factors = {
            f"T{i}": make_factor_scores(ticker=f"T{i}", composite_score=i * 0.3)
            for i in range(1, 8)
        }
        insider = {
            f"T{i}": make_insider(ticker=f"T{i}", signal="neutral")
            for i in range(1, 8)
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)

        total_weight = sum(s.suggested_weight for s in result.values())
        assert total_weight <= 1.0 + 1e-6, f"Total weight {total_weight} exceeds 1.0"

    def test_max_weight_per_stock(self):
        """No single stock should exceed MAX_POSITION_WEIGHT."""
        # Only 2 stocks: one super bullish, so it might get most weight
        technical = {
            "MEGA": make_signal(ticker="MEGA", score=10),
            "TINY": make_signal(ticker="TINY", score=1),
        }
        factors = {
            "MEGA": make_factor_scores(ticker="MEGA", composite_score=3.0),
            "TINY": make_factor_scores(ticker="TINY", composite_score=0.1),
        }
        insider = {
            "MEGA": make_insider(ticker="MEGA", signal="bullish"),
            "TINY": make_insider(ticker="TINY", signal="neutral"),
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)

        for ticker, score in result.items():
            assert score.suggested_weight <= MAX_POSITION_WEIGHT + 1e-6, (
                f"{ticker} weight {score.suggested_weight} exceeds max {MAX_POSITION_WEIGHT}"
            )

    def test_regime_scaling_reduces_scores(self):
        """Bear/crisis regime_scale should reduce combined scores."""
        technical = {"AAPL": make_signal(ticker="AAPL", score=5)}
        factors = {"AAPL": make_factor_scores(ticker="AAPL", composite_score=1.0)}
        insider = {"AAPL": make_insider(ticker="AAPL", signal="bullish")}

        bull_result = combine_signals(technical, factors, insider, regime_scale=1.0)
        bear_result = combine_signals(technical, factors, insider, regime_scale=0.5)
        crisis_result = combine_signals(technical, factors, insider, regime_scale=0.2)

        assert bear_result["AAPL"].combined_score < bull_result["AAPL"].combined_score
        assert crisis_result["AAPL"].combined_score < bear_result["AAPL"].combined_score

    def test_empty_technical_returns_empty(self):
        """No technical signals -> no results."""
        result = combine_signals({}, {}, {})
        assert result == {}

    def test_missing_factors_defaults_neutral(self):
        """Stocks without factor data should get neutral factor score."""
        technical = {"AAPL": make_signal(ticker="AAPL", score=5)}
        # No factor or insider data
        result = combine_signals(technical, {}, {}, regime_scale=1.0)

        assert "AAPL" in result
        assert result["AAPL"].factor_score == 0.5  # neutral
        assert result["AAPL"].insider_score == 0.5  # neutral

    def test_weights_sum_correctly(self):
        """The weight constants should sum to 1.0."""
        total = WEIGHT_TECHNICAL + WEIGHT_FACTOR + WEIGHT_INSIDER + WEIGHT_REGIME
        assert abs(total - 1.0) < 1e-10


# ===================================================================
# Format report tests
# ===================================================================

class TestFormatCombinedReport:
    def setup_method(self):
        from api.quant.ml_combiner import _cache
        _cache.clear()

    def test_format_empty(self):
        """Empty scores should produce 'no data' message."""
        report = format_combined_report({})
        assert "No combined signal data" in report

    def test_format_contains_header(self):
        """Report should contain the header."""
        technical = {"AAPL": make_signal(ticker="AAPL", score=3)}
        factors = {"AAPL": make_factor_scores(ticker="AAPL", composite_score=0.5)}
        insider = {"AAPL": make_insider(ticker="AAPL", signal="neutral")}

        result = combine_signals(technical, factors, insider, regime_scale=1.0)
        report = format_combined_report(result)

        assert "COMBINED SIGNAL REPORT" in report

    def test_format_contains_ticker(self):
        """Report should mention the ticker."""
        technical = {"NVDA": make_signal(ticker="NVDA", score=7)}
        factors = {"NVDA": make_factor_scores(ticker="NVDA", composite_score=1.5)}
        insider = {"NVDA": make_insider(ticker="NVDA", signal="bullish")}

        result = combine_signals(technical, factors, insider, regime_scale=1.0)
        report = format_combined_report(result)

        assert "NVDA" in report

    def test_format_sorted_by_score(self):
        """Tickers should appear sorted by combined score (highest first)."""
        technical = {
            "LOW": make_signal(ticker="LOW", score=-5),
            "HIGH": make_signal(ticker="HIGH", score=8),
            "MID": make_signal(ticker="MID", score=0),
        }
        factors = {
            "LOW": make_factor_scores(ticker="LOW", composite_score=-1.0),
            "HIGH": make_factor_scores(ticker="HIGH", composite_score=2.0),
            "MID": make_factor_scores(ticker="MID", composite_score=0.0),
        }
        insider = {
            "LOW": make_insider(ticker="LOW", signal="bearish"),
            "HIGH": make_insider(ticker="HIGH", signal="bullish"),
            "MID": make_insider(ticker="MID", signal="neutral"),
        }

        result = combine_signals(technical, factors, insider, regime_scale=1.0)
        report = format_combined_report(result)

        high_pos = report.index("HIGH")
        mid_pos = report.index("MID")
        low_pos = report.index("LOW")
        assert high_pos < mid_pos < low_pos

    def test_format_shows_regime_scale(self):
        """Report should show the regime scale."""
        technical = {"AAPL": make_signal(ticker="AAPL", score=3)}
        factors = {"AAPL": make_factor_scores(ticker="AAPL", composite_score=0.5)}
        insider = {"AAPL": make_insider(ticker="AAPL", signal="neutral")}

        result = combine_signals(technical, factors, insider, regime_scale=0.5)
        report = format_combined_report(result)

        assert "Regime scale" in report

    def test_format_shows_strong_buy_section(self):
        """Report should highlight strong buy signals."""
        technical = {"MEGA": make_signal(ticker="MEGA", score=10)}
        factors = {"MEGA": make_factor_scores(ticker="MEGA", composite_score=3.0)}
        insider = {"MEGA": make_insider(ticker="MEGA", signal="bullish")}

        result = combine_signals(technical, factors, insider, regime_scale=1.0)
        report = format_combined_report(result)

        # The stock should be a strong buy
        if result["MEGA"].signal == "strong_buy":
            assert "STRONG BUY" in report

    def test_format_shows_sell_section(self):
        """Report should highlight sell signals."""
        technical = {"DUMP": make_signal(ticker="DUMP", score=-10)}
        factors = {"DUMP": make_factor_scores(ticker="DUMP", composite_score=-3.0)}
        insider = {"DUMP": make_insider(ticker="DUMP", signal="bearish")}

        result = combine_signals(technical, factors, insider, regime_scale=1.0)
        report = format_combined_report(result)

        if result["DUMP"].signal in ("sell", "strong_sell"):
            assert "SELL" in report
