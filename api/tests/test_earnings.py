"""Tests for earnings and fundamental event analysis."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from api.quant.earnings import (
    EarningsInsight,
    analyze_earnings_news,
    format_earnings_report,
    _cache,
)


# ===================================================================
# analyze_earnings_news tests
# ===================================================================

class TestAnalyzeEarningsNewsPositive:
    def test_analyze_earnings_news_with_positive_headlines(self):
        """Positive earnings headlines should produce positive sentiment."""
        _cache.clear()
        mock_news = [
            "AAPL beats earnings expectations with record revenue",
            "Apple surges after strong quarterly results",
            "AAPL EPS exceeds analyst forecast",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["AAPL"])

        assert "AAPL" in results
        insight = results["AAPL"]
        assert insight.has_recent_earnings is True
        assert insight.sentiment == "positive"
        assert len(insight.key_points) > 0

    def test_analyze_earnings_news_with_negative_headlines(self):
        """Negative earnings headlines should produce negative sentiment."""
        _cache.clear()
        mock_news = [
            "TSLA misses earnings estimates, revenue disappoints",
            "Tesla warns of declining margins",
            "TSLA quarterly profit falls short of expectations",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["TSLA"])

        assert "TSLA" in results
        insight = results["TSLA"]
        assert insight.has_recent_earnings is True
        assert insight.sentiment == "negative"


class TestAnalyzeEarningsNewsNoEarnings:
    def test_analyze_earnings_news_no_earnings(self):
        """Non-earnings news should result in has_recent_earnings=False."""
        _cache.clear()
        mock_news = [
            "AAPL launches new iPhone model",
            "Apple opens new store in Tokyo",
            "Tim Cook speaks at conference",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["AAPL"])

        assert "AAPL" in results
        insight = results["AAPL"]
        assert insight.has_recent_earnings is False
        assert insight.sentiment == "unknown"
        assert insight.key_points == []
        assert insight.forward_guidance == "unknown"

    def test_analyze_earnings_news_empty_news(self):
        """Empty news list should result in has_recent_earnings=False."""
        _cache.clear()
        with patch("api.quant.earnings.get_stock_news", return_value=[]):
            results = analyze_earnings_news(["MSFT"])

        insight = results["MSFT"]
        assert insight.has_recent_earnings is False
        assert insight.sentiment == "unknown"


class TestEarningsSentimentDetection:
    def test_earnings_sentiment_neutral_when_balanced(self):
        """Equal positive and negative words should produce neutral sentiment."""
        _cache.clear()
        mock_news = [
            "GOOG beats on revenue but misses on earnings",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["GOOG"])

        insight = results["GOOG"]
        assert insight.has_recent_earnings is True
        assert insight.sentiment == "neutral"

    def test_earnings_sentiment_positive_when_more_positive_words(self):
        """More positive words than negative should produce positive sentiment."""
        _cache.clear()
        mock_news = [
            "Company beats earnings with record revenue and strong growth",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["XYZ"])

        insight = results["XYZ"]
        assert insight.sentiment == "positive"

    def test_earnings_sentiment_negative_when_more_negative_words(self):
        """More negative words than positive should produce negative sentiment."""
        _cache.clear()
        mock_news = [
            "Company disappoints with weak earnings and declining profit",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["BAD"])

        insight = results["BAD"]
        assert insight.sentiment == "negative"


class TestGuidanceDetection:
    def test_guidance_raised(self):
        """Headlines with 'raise' should detect guidance as raised."""
        _cache.clear()
        mock_news = [
            "Company raises full-year earnings guidance",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["UP"])

        assert results["UP"].forward_guidance == "raised"

    def test_guidance_lowered(self):
        """Headlines with 'cut' or 'lower' should detect guidance as lowered."""
        _cache.clear()
        mock_news = [
            "Company cuts earnings forecast amid lower demand",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["DOWN"])

        assert results["DOWN"].forward_guidance == "lowered"

    def test_guidance_maintained(self):
        """Headlines with 'maintain' or 'reiterate' should detect guidance as maintained."""
        _cache.clear()
        mock_news = [
            "Company reiterates full-year earnings outlook",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["SAME"])

        assert results["SAME"].forward_guidance == "maintained"

    def test_guidance_unknown_when_no_keywords(self):
        """No guidance keywords should produce 'unknown'."""
        _cache.clear()
        mock_news = [
            "Company reports quarterly earnings results",
        ]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news):
            results = analyze_earnings_news(["NEUT"])

        assert results["NEUT"].forward_guidance == "unknown"


# ===================================================================
# format_earnings_report tests
# ===================================================================

class TestFormatEarningsReport:
    def test_format_earnings_report_with_data(self):
        """Report should contain ticker and sentiment info."""
        insights = {
            "AAPL": EarningsInsight(
                ticker="AAPL", has_recent_earnings=True,
                sentiment="positive", key_points=["Apple beats Q4 estimates"],
                forward_guidance="raised"
            ),
        }
        report = format_earnings_report(insights)
        assert "AAPL" in report
        assert "positive" in report
        assert "raised" in report
        assert "EARNINGS" in report

    def test_format_earnings_report_empty_when_no_earnings(self):
        """Report should be empty string when no tickers have earnings."""
        insights = {
            "AAPL": EarningsInsight(
                ticker="AAPL", has_recent_earnings=False,
                sentiment="unknown", key_points=[], forward_guidance="unknown"
            ),
        }
        report = format_earnings_report(insights)
        assert report == ""

    def test_format_earnings_report_truncates_key_points(self):
        """Key points should be truncated to 100 chars max."""
        long_point = "A" * 200
        insights = {
            "MSFT": EarningsInsight(
                ticker="MSFT", has_recent_earnings=True,
                sentiment="neutral", key_points=[long_point],
                forward_guidance="maintained"
            ),
        }
        report = format_earnings_report(insights)
        # Each line with a key point should be <= 100 chars of the point itself
        for line in report.split("\n"):
            if line.strip().startswith("- "):
                # The point text (after "      - ") should be <= 100 chars
                point_text = line.strip()[2:]
                assert len(point_text) <= 100

    def test_format_earnings_report_limits_key_points_to_two(self):
        """Only first 2 key points should appear in report."""
        insights = {
            "GOOG": EarningsInsight(
                ticker="GOOG", has_recent_earnings=True,
                sentiment="positive",
                key_points=["Point 1 earnings", "Point 2 earnings", "Point 3 earnings"],
                forward_guidance="unknown"
            ),
        }
        report = format_earnings_report(insights)
        assert "Point 1" in report
        assert "Point 2" in report
        assert "Point 3" not in report

    def test_format_earnings_report_empty_dict(self):
        """Empty dict should produce empty string."""
        report = format_earnings_report({})
        assert report == ""


# ===================================================================
# Cache tests
# ===================================================================

class TestEarningsCache:
    def test_cache_hit_returns_same_result(self):
        """Second call should use cache and return same result."""
        _cache.clear()
        mock_news = ["Company beats earnings expectations"]
        with patch("api.quant.earnings.get_stock_news", return_value=mock_news) as mock_fn:
            results1 = analyze_earnings_news(["AAPL"])
            results2 = analyze_earnings_news(["AAPL"])

        # get_stock_news should only be called once (second call uses cache)
        assert mock_fn.call_count == 1
        assert results1["AAPL"].sentiment == results2["AAPL"].sentiment
