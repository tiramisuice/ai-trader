"""Tests for multi-factor stock scoring model."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
import numpy as np
import pandas as pd

from api.quant.factors import (
    FactorScores,
    _zscore,
    _classify_factor_signal,
    _safe_get,
    compute_factor_scores,
    format_factor_report,
)


# ---------------------------------------------------------------------------
# Helper: build a FactorScores with sensible defaults + custom overrides
# ---------------------------------------------------------------------------

def make_factor_scores(**overrides) -> FactorScores:
    """Create a FactorScores with defaults; override any field via kwargs."""
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


# ===================================================================
# Z-score computation tests
# ===================================================================

class TestZScore:
    def test_zscore_normal(self):
        """Z-scores of a normal list should have mean ~0 and std ~1."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        zs = _zscore(values)
        assert len(zs) == 5
        assert abs(np.mean(zs)) < 1e-10
        assert abs(np.std(zs) - 1.0) < 1e-10

    def test_zscore_with_none(self):
        """None values should get z-score of 0."""
        values = [1.0, None, 3.0, None, 5.0]
        zs = _zscore(values)
        assert zs[1] == 0.0
        assert zs[3] == 0.0

    def test_zscore_all_none(self):
        """All None values should return all zeros."""
        values = [None, None, None]
        zs = _zscore(values)
        assert zs == [0.0, 0.0, 0.0]

    def test_zscore_single_value(self):
        """Single non-None value should return zeros (not enough data)."""
        values = [5.0, None, None]
        zs = _zscore(values)
        # With only 1 valid point, std=0, so all zeros
        assert zs == [0.0, 0.0, 0.0]

    def test_zscore_identical_values(self):
        """Identical values should return all zeros (std=0)."""
        values = [3.0, 3.0, 3.0]
        zs = _zscore(values)
        assert zs == [0.0, 0.0, 0.0]

    def test_zscore_two_values(self):
        """Two values should produce valid z-scores."""
        values = [1.0, 3.0]
        zs = _zscore(values)
        assert len(zs) == 2
        # The lower value should have negative z-score
        assert zs[0] < 0
        assert zs[1] > 0


# ===================================================================
# Signal classification tests
# ===================================================================

class TestFactorSignalClassification:
    def test_strong_buy(self):
        """Composite >= 1.0 should be strong_buy."""
        assert _classify_factor_signal(1.0) == "strong_buy"
        assert _classify_factor_signal(2.5) == "strong_buy"

    def test_buy(self):
        """Composite 0.3 to 1.0 should be buy."""
        assert _classify_factor_signal(0.3) == "buy"
        assert _classify_factor_signal(0.7) == "buy"
        assert _classify_factor_signal(0.99) == "buy"

    def test_neutral(self):
        """Composite -0.3 to 0.3 should be neutral."""
        assert _classify_factor_signal(0.0) == "neutral"
        assert _classify_factor_signal(0.29) == "neutral"
        assert _classify_factor_signal(-0.29) == "neutral"

    def test_sell(self):
        """Composite -1.0 to -0.3 should be sell."""
        assert _classify_factor_signal(-0.3) == "sell"
        assert _classify_factor_signal(-0.7) == "sell"
        assert _classify_factor_signal(-0.99) == "sell"

    def test_strong_sell(self):
        """Composite <= -1.0 should be strong_sell."""
        assert _classify_factor_signal(-1.0) == "strong_sell"
        assert _classify_factor_signal(-2.0) == "strong_sell"


# ===================================================================
# Safe get helper tests
# ===================================================================

class TestSafeGet:
    def test_normal_value(self):
        assert _safe_get({"pe": 25.0}, "pe") == 25.0

    def test_missing_key(self):
        assert _safe_get({"pe": 25.0}, "roe") is None

    def test_none_value(self):
        assert _safe_get({"pe": None}, "pe") is None

    def test_nan_value(self):
        assert _safe_get({"pe": float("nan")}, "pe") is None

    def test_inf_value(self):
        assert _safe_get({"pe": float("inf")}, "pe") is None

    def test_string_convertible(self):
        assert _safe_get({"pe": "25.0"}, "pe") == 25.0


# ===================================================================
# Factor score computation tests (mocked yfinance)
# ===================================================================

def _make_mock_ticker(
    info: dict,
    close_prices: list[float] | None = None,
):
    """Create a mock yfinance Ticker object."""
    mock = MagicMock()
    mock.info = info

    if close_prices is None:
        # Generate 260 days of prices (enough for 12-month momentum)
        np.random.seed(42)
        close_prices = list(100 + np.cumsum(np.random.randn(260) * 0.5))

    n = len(close_prices)
    dates = pd.date_range(end="2026-03-31", periods=n, freq="B")
    hist = pd.DataFrame({
        "Close": close_prices,
        "High": [p * 1.01 for p in close_prices],
        "Low": [p * 0.99 for p in close_prices],
        "Volume": [1_000_000] * n,
    }, index=dates)
    mock.history.return_value = hist
    return mock


class TestComputeFactorScores:
    def test_factor_scores_computation(self):
        """Factor scores should be computed for a batch of mocked stocks."""
        infos = {
            "AAPL": {
                "trailingEps": 6.0, "bookValue": 4.0, "sharesOutstanding": 15e9,
                "marketCap": 3000e9, "returnOnEquity": 0.40,
                "profitMargins": 0.25, "debtToEquity": 150.0,
            },
            "MSFT": {
                "trailingEps": 10.0, "bookValue": 25.0, "sharesOutstanding": 7.5e9,
                "marketCap": 2800e9, "returnOnEquity": 0.35,
                "profitMargins": 0.35, "debtToEquity": 40.0,
            },
            "TSLA": {
                "trailingEps": 3.0, "bookValue": 20.0, "sharesOutstanding": 3.2e9,
                "marketCap": 800e9, "returnOnEquity": 0.20,
                "profitMargins": 0.10, "debtToEquity": 10.0,
            },
        }

        def mock_ticker_factory(ticker):
            np.random.seed(hash(ticker) % 2**31)
            prices = list(100 + np.cumsum(np.random.randn(260) * 0.5))
            return _make_mock_ticker(infos.get(ticker, {}), prices)

        # Clear cache before test
        from api.quant.factors import _cache
        _cache.clear()

        with patch("api.quant.factors.fetch_info", side_effect=lambda t: mock_ticker_factory(t).info), \
             patch("api.quant.factors.fetch_history", side_effect=lambda t, p: mock_ticker_factory(t).history()):
            scores = compute_factor_scores(["AAPL", "MSFT", "TSLA"])

        assert len(scores) == 3
        assert "AAPL" in scores
        assert "MSFT" in scores
        assert "TSLA" in scores

        for t, s in scores.items():
            assert isinstance(s, FactorScores)
            assert s.ticker == t
            # All scores should be finite
            assert np.isfinite(s.value_score)
            assert np.isfinite(s.momentum_score)
            assert np.isfinite(s.quality_score)
            assert np.isfinite(s.size_score)
            assert np.isfinite(s.volatility_score)
            assert np.isfinite(s.composite_score)

    def test_composite_score_range(self):
        """Composite scores should be reasonable z-score values."""
        infos = {
            "A": {
                "trailingEps": 5.0, "bookValue": 10.0, "sharesOutstanding": 1e9,
                "marketCap": 50e9, "returnOnEquity": 0.30,
                "profitMargins": 0.20, "debtToEquity": 50.0,
            },
            "B": {
                "trailingEps": 2.0, "bookValue": 5.0, "sharesOutstanding": 2e9,
                "marketCap": 100e9, "returnOnEquity": 0.10,
                "profitMargins": 0.05, "debtToEquity": 200.0,
            },
        }

        def mock_ticker_factory(ticker):
            np.random.seed(hash(ticker) % 2**31)
            prices = list(100 + np.cumsum(np.random.randn(260) * 0.5))
            return _make_mock_ticker(infos.get(ticker, {}), prices)

        from api.quant.factors import _cache
        _cache.clear()

        with patch("api.quant.factors.fetch_info", side_effect=lambda t: mock_ticker_factory(t).info), \
             patch("api.quant.factors.fetch_history", side_effect=lambda t, p: mock_ticker_factory(t).history()):
            scores = compute_factor_scores(["A", "B"])

        for s in scores.values():
            # Composite should be within reasonable z-score range
            assert -5.0 <= s.composite_score <= 5.0

    def test_factor_signal_matches_composite(self):
        """Factor signal should correspond correctly to composite score."""
        s = make_factor_scores(composite_score=1.5, factor_signal="strong_buy")
        assert s.factor_signal == _classify_factor_signal(s.composite_score)

        s2 = make_factor_scores(composite_score=-0.5, factor_signal="sell")
        assert s2.factor_signal == _classify_factor_signal(s2.composite_score)

    def test_empty_tickers_returns_empty(self):
        """Empty ticker list should return empty dict."""
        from api.quant.factors import _cache
        _cache.clear()

        scores = compute_factor_scores([])
        assert scores == {}

    def test_all_failures_returns_empty(self):
        """If all tickers fail to fetch, return empty dict."""
        from api.quant.factors import _cache
        _cache.clear()

        with patch("api.quant.factors.fetch_info", side_effect=Exception("API error")), \
             patch("api.quant.factors.fetch_history", side_effect=Exception("API error")):
            scores = compute_factor_scores(["BAD1", "BAD2"])

        assert scores == {}


# ===================================================================
# Format report tests
# ===================================================================

class TestFormatFactorReport:
    def test_format_empty(self):
        """Empty scores should return 'no data' message."""
        report = format_factor_report({})
        assert "No factor data" in report

    def test_format_contains_header(self):
        """Report should contain header."""
        scores = {"AAPL": make_factor_scores(ticker="AAPL")}
        report = format_factor_report(scores)
        assert "MULTI-FACTOR SCORE REPORT" in report

    def test_format_contains_ticker(self):
        """Report should mention the ticker."""
        scores = {"AAPL": make_factor_scores(ticker="AAPL", composite_score=0.5, factor_signal="buy")}
        report = format_factor_report(scores)
        assert "AAPL" in report
        assert "BUY" in report

    def test_format_sorted_by_composite(self):
        """Tickers should be sorted by composite score (highest first)."""
        scores = {
            "LOW": make_factor_scores(ticker="LOW", composite_score=-0.5, factor_signal="sell"),
            "HIGH": make_factor_scores(ticker="HIGH", composite_score=1.5, factor_signal="strong_buy"),
            "MID": make_factor_scores(ticker="MID", composite_score=0.2, factor_signal="neutral"),
        }
        report = format_factor_report(scores)
        high_pos = report.index("HIGH")
        mid_pos = report.index("MID")
        low_pos = report.index("LOW")
        assert high_pos < mid_pos < low_pos

    def test_format_includes_raw_data(self):
        """Report should include raw factor data like ROE and profit margin."""
        scores = {
            "MSFT": make_factor_scores(
                ticker="MSFT",
                roe=0.35,
                profit_margin=0.30,
                market_cap=2800e9,
                momentum_12_1=0.15,
            ),
        }
        report = format_factor_report(scores)
        assert "ROE=" in report
        assert "Margin=" in report
        assert "MCap=" in report

    def test_format_handles_none_values(self):
        """Report should handle None raw values gracefully."""
        scores = {
            "UNKNOWN": make_factor_scores(
                ticker="UNKNOWN",
                earnings_yield=None,
                roe=None,
                profit_margin=None,
                market_cap=None,
                momentum_12_1=None,
                momentum_6_1=None,
                volatility_60d=None,
                book_to_market=None,
                debt_to_equity=None,
            ),
        }
        report = format_factor_report(scores)
        assert "N/A" in report
        # Should not crash
        assert "UNKNOWN" in report
