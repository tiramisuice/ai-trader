"""Tests for anomaly detection — unusual signal combinations."""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field

from api.quant.anomaly import (
    AnomalyAlert,
    detect_anomalies,
    format_anomaly_report,
)


# ---------------------------------------------------------------------------
# Mock dataclasses to simulate TechnicalSignals, FactorScores, etc.
# ---------------------------------------------------------------------------

@dataclass
class MockSignal:
    """Minimal mock for TechnicalSignals."""
    ticker: str = "TEST"
    price: float = 100.0
    rsi_14: float | None = 50.0
    rsi_signal: str = "neutral"
    high_volume: bool = False
    volume_ratio: float = 1.0
    death_cross: bool = False
    golden_cross: bool = False
    score: int = 0
    signal: str = "neutral"
    bb_upper: float | None = 110.0
    bb_lower: float | None = 90.0
    atr_14: float | None = 2.5


@dataclass
class MockFactors:
    """Minimal mock for FactorScores."""
    ticker: str = "TEST"
    composite_score: float = 0.0


@dataclass
class MockInsider:
    """Minimal mock for InsiderSignal."""
    ticker: str = "TEST"
    signal: str = "neutral"
    net_insider_buys_30d: int = 0
    details: list[str] = field(default_factory=list)


@dataclass
class MockEarnings:
    """Minimal mock for EarningsInsight."""
    ticker: str = "TEST"
    has_recent_earnings: bool = False
    sentiment: str = "unknown"
    key_points: list[str] = field(default_factory=list)
    forward_guidance: str = "unknown"


# ===================================================================
# Volume crash detection
# ===================================================================

class TestVolumeCrashDetection:
    def test_volume_crash_detected(self):
        """High volume + low RSI should trigger VOLUME_CRASH alert."""
        signals = {"AAPL": MockSignal(
            ticker="AAPL", high_volume=True, volume_ratio=2.5, rsi_14=30.0
        )}
        alerts = detect_anomalies(signals, {}, {}, {})

        volume_alerts = [a for a in alerts if a.alert_type == "VOLUME_CRASH"]
        assert len(volume_alerts) == 1
        assert volume_alerts[0].severity == "warning"
        assert "AAPL" in volume_alerts[0].ticker

    def test_no_volume_crash_normal_volume(self):
        """Normal volume should not trigger VOLUME_CRASH."""
        signals = {"AAPL": MockSignal(
            ticker="AAPL", high_volume=False, volume_ratio=1.0, rsi_14=30.0
        )}
        alerts = detect_anomalies(signals, {}, {}, {})
        assert not any(a.alert_type == "VOLUME_CRASH" for a in alerts)

    def test_no_volume_crash_high_rsi(self):
        """High volume but high RSI should not trigger VOLUME_CRASH."""
        signals = {"AAPL": MockSignal(
            ticker="AAPL", high_volume=True, volume_ratio=2.5, rsi_14=60.0
        )}
        alerts = detect_anomalies(signals, {}, {}, {})
        assert not any(a.alert_type == "VOLUME_CRASH" for a in alerts)


# ===================================================================
# Insider exit detection
# ===================================================================

class TestInsiderExitDetection:
    def test_insider_exit_detected(self):
        """Bearish insider + death cross should trigger INSIDER_EXIT."""
        signals = {"TSLA": MockSignal(ticker="TSLA", death_cross=True)}
        insider = {"TSLA": MockInsider(ticker="TSLA", signal="bearish")}
        alerts = detect_anomalies(signals, {}, insider, {})

        exit_alerts = [a for a in alerts if a.alert_type == "INSIDER_EXIT"]
        assert len(exit_alerts) == 1
        assert exit_alerts[0].severity == "critical"

    def test_no_insider_exit_without_death_cross(self):
        """Bearish insider without death cross should not trigger."""
        signals = {"TSLA": MockSignal(ticker="TSLA", death_cross=False)}
        insider = {"TSLA": MockInsider(ticker="TSLA", signal="bearish")}
        alerts = detect_anomalies(signals, {}, insider, {})
        assert not any(a.alert_type == "INSIDER_EXIT" for a in alerts)

    def test_no_insider_exit_without_bearish_insider(self):
        """Death cross without bearish insider should not trigger."""
        signals = {"TSLA": MockSignal(ticker="TSLA", death_cross=True)}
        insider = {"TSLA": MockInsider(ticker="TSLA", signal="neutral")}
        alerts = detect_anomalies(signals, {}, insider, {})
        assert not any(a.alert_type == "INSIDER_EXIT" for a in alerts)


# ===================================================================
# Insider buy dip detection
# ===================================================================

class TestInsiderBuyDipDetection:
    def test_insider_buy_dip_detected(self):
        """Bullish insider + oversold RSI should trigger INSIDER_BUY_DIP."""
        signals = {"NVDA": MockSignal(ticker="NVDA", rsi_14=25.0, rsi_signal="oversold")}
        insider = {"NVDA": MockInsider(ticker="NVDA", signal="bullish")}
        alerts = detect_anomalies(signals, {}, insider, {})

        buy_alerts = [a for a in alerts if a.alert_type == "INSIDER_BUY_DIP"]
        assert len(buy_alerts) == 1
        assert buy_alerts[0].severity == "info"

    def test_no_insider_buy_dip_neutral_rsi(self):
        """Bullish insider without oversold RSI should not trigger."""
        signals = {"NVDA": MockSignal(ticker="NVDA", rsi_14=50.0, rsi_signal="neutral")}
        insider = {"NVDA": MockInsider(ticker="NVDA", signal="bullish")}
        alerts = detect_anomalies(signals, {}, insider, {})
        assert not any(a.alert_type == "INSIDER_BUY_DIP" for a in alerts)


# ===================================================================
# Technical-Factor divergence detection
# ===================================================================

class TestTechFactorDivergence:
    def test_tech_factor_divergence_detected(self):
        """Negative tech score + positive factor score should trigger divergence."""
        signals = {"MSFT": MockSignal(ticker="MSFT", score=-4)}
        factors = {"MSFT": MockFactors(ticker="MSFT", composite_score=0.8)}
        alerts = detect_anomalies(signals, factors, {}, {})

        div_alerts = [a for a in alerts if a.alert_type == "TECH_FACTOR_DIVERGENCE"]
        assert len(div_alerts) == 1
        assert div_alerts[0].severity == "info"
        assert "value opportunity" in div_alerts[0].message.lower() or "value trap" in div_alerts[0].message.lower()

    def test_no_divergence_aligned_signals(self):
        """Both positive tech and factor should not trigger divergence."""
        signals = {"MSFT": MockSignal(ticker="MSFT", score=3)}
        factors = {"MSFT": MockFactors(ticker="MSFT", composite_score=0.8)}
        alerts = detect_anomalies(signals, factors, {}, {})
        assert not any(a.alert_type == "TECH_FACTOR_DIVERGENCE" for a in alerts)

    def test_no_divergence_low_factor_score(self):
        """Negative tech + low factor should not trigger divergence."""
        signals = {"MSFT": MockSignal(ticker="MSFT", score=-4)}
        factors = {"MSFT": MockFactors(ticker="MSFT", composite_score=0.2)}
        alerts = detect_anomalies(signals, factors, {}, {})
        assert not any(a.alert_type == "TECH_FACTOR_DIVERGENCE" for a in alerts)


# ===================================================================
# Earnings momentum detection
# ===================================================================

class TestEarningsMomentumDetection:
    def test_earnings_momentum_detected(self):
        """Positive earnings + strong tech score should trigger EARNINGS_MOMENTUM."""
        signals = {"GOOG": MockSignal(ticker="GOOG", score=4)}
        earnings = {"GOOG": MockEarnings(ticker="GOOG", sentiment="positive")}
        alerts = detect_anomalies(signals, {}, {}, earnings)

        mom_alerts = [a for a in alerts if a.alert_type == "EARNINGS_MOMENTUM"]
        assert len(mom_alerts) == 1
        assert mom_alerts[0].severity == "info"

    def test_no_earnings_momentum_weak_tech(self):
        """Positive earnings + weak tech should not trigger."""
        signals = {"GOOG": MockSignal(ticker="GOOG", score=1)}
        earnings = {"GOOG": MockEarnings(ticker="GOOG", sentiment="positive")}
        alerts = detect_anomalies(signals, {}, {}, earnings)
        assert not any(a.alert_type == "EARNINGS_MOMENTUM" for a in alerts)

    def test_no_earnings_momentum_negative_earnings(self):
        """Negative earnings + strong tech should not trigger."""
        signals = {"GOOG": MockSignal(ticker="GOOG", score=4)}
        earnings = {"GOOG": MockEarnings(ticker="GOOG", sentiment="negative")}
        alerts = detect_anomalies(signals, {}, {}, earnings)
        assert not any(a.alert_type == "EARNINGS_MOMENTUM" for a in alerts)


# ===================================================================
# Bollinger squeeze detection
# ===================================================================

class TestBollingerSqueezeDetection:
    def test_bollinger_squeeze_detected(self):
        """Narrow Bollinger Bands should trigger BOLLINGER_SQUEEZE."""
        # bb_width = (upper - lower) / price = (101.5 - 98.5) / 100 = 0.03 < 0.04
        signals = {"META": MockSignal(
            ticker="META", price=100.0,
            bb_upper=101.5, bb_lower=98.5, atr_14=1.0
        )}
        alerts = detect_anomalies(signals, {}, {}, {})

        squeeze_alerts = [a for a in alerts if a.alert_type == "BOLLINGER_SQUEEZE"]
        assert len(squeeze_alerts) == 1
        assert squeeze_alerts[0].severity == "info"
        assert "squeezed" in squeeze_alerts[0].message.lower()

    def test_no_bollinger_squeeze_wide_bands(self):
        """Wide Bollinger Bands should not trigger."""
        # bb_width = (120 - 80) / 100 = 0.40 > 0.04
        signals = {"META": MockSignal(
            ticker="META", price=100.0,
            bb_upper=120.0, bb_lower=80.0, atr_14=5.0
        )}
        alerts = detect_anomalies(signals, {}, {}, {})
        assert not any(a.alert_type == "BOLLINGER_SQUEEZE" for a in alerts)

    def test_no_bollinger_squeeze_missing_data(self):
        """Missing BB data should not trigger."""
        signals = {"META": MockSignal(
            ticker="META", price=100.0,
            bb_upper=None, bb_lower=None, atr_14=1.0
        )}
        alerts = detect_anomalies(signals, {}, {}, {})
        assert not any(a.alert_type == "BOLLINGER_SQUEEZE" for a in alerts)


# ===================================================================
# No anomalies when normal
# ===================================================================

class TestNoAnomaliesNormal:
    def test_no_anomalies_when_normal(self):
        """Normal signals should produce zero alerts."""
        signals = {"AAPL": MockSignal(
            ticker="AAPL", price=150.0, rsi_14=50.0, rsi_signal="neutral",
            high_volume=False, volume_ratio=1.0, death_cross=False,
            score=0, signal="neutral",
            bb_upper=160.0, bb_lower=140.0, atr_14=2.0
        )}
        factors = {"AAPL": MockFactors(ticker="AAPL", composite_score=0.0)}
        insider = {"AAPL": MockInsider(ticker="AAPL", signal="neutral")}
        earnings = {"AAPL": MockEarnings(ticker="AAPL", sentiment="unknown")}

        alerts = detect_anomalies(signals, factors, insider, earnings)
        assert len(alerts) == 0

    def test_no_anomalies_empty_inputs(self):
        """Empty dicts should produce zero alerts."""
        alerts = detect_anomalies({}, {}, {}, {})
        assert len(alerts) == 0


# ===================================================================
# Severity sorting
# ===================================================================

class TestSeveritySorting:
    def test_severity_sorting(self):
        """Alerts should be sorted: critical > warning > info."""
        signals = {
            "A": MockSignal(ticker="A", death_cross=True),
            "B": MockSignal(ticker="B", high_volume=True, volume_ratio=3.0, rsi_14=25.0),
            "C": MockSignal(ticker="C", score=5, rsi_14=50.0),
        }
        insider = {"A": MockInsider(ticker="A", signal="bearish")}
        earnings = {"C": MockEarnings(ticker="C", sentiment="positive")}

        alerts = detect_anomalies(signals, {}, insider, earnings)

        # Should have at least 2 alerts of different severities
        assert len(alerts) >= 2

        # Check ordering
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        for i in range(len(alerts) - 1):
            current = severity_order.get(alerts[i].severity, 3)
            next_val = severity_order.get(alerts[i + 1].severity, 3)
            assert current <= next_val, f"Severity not sorted: {alerts[i].severity} before {alerts[i+1].severity}"


# ===================================================================
# format_anomaly_report tests
# ===================================================================

class TestFormatAnomalyReport:
    def test_format_anomaly_report_with_alerts(self):
        """Report should contain alert type and ticker."""
        alerts = [
            AnomalyAlert(ticker="AAPL", severity="critical", alert_type="INSIDER_EXIT",
                        message="Insider selling + Death Cross"),
            AnomalyAlert(ticker="TSLA", severity="info", alert_type="BOLLINGER_SQUEEZE",
                        message="Bollinger Bands squeezed (3.0% width)"),
        ]
        report = format_anomaly_report(alerts)
        assert "ANOMALY ALERTS:" in report
        assert "AAPL" in report
        assert "TSLA" in report
        assert "INSIDER_EXIT" in report
        assert "BOLLINGER_SQUEEZE" in report

    def test_format_anomaly_report_empty(self):
        """Empty alerts should produce empty string."""
        report = format_anomaly_report([])
        assert report == ""

    def test_format_anomaly_report_icons(self):
        """Report should contain severity icons."""
        alerts = [
            AnomalyAlert(ticker="X", severity="critical", alert_type="TEST", message="test"),
            AnomalyAlert(ticker="Y", severity="warning", alert_type="TEST", message="test"),
            AnomalyAlert(ticker="Z", severity="info", alert_type="TEST", message="test"),
        ]
        report = format_anomaly_report(alerts)
        # Should contain the icons for each severity
        assert "\U0001f6a8" in report  # critical
        assert "\u26a0" in report     # warning
        assert "\U0001f4a1" in report  # info


# ===================================================================
# Multiple tickers test
# ===================================================================

class TestMultipleTickers:
    def test_multiple_tickers_independent(self):
        """Each ticker's anomalies should be independent."""
        signals = {
            "AAPL": MockSignal(ticker="AAPL", high_volume=True, volume_ratio=2.0, rsi_14=30.0),
            "MSFT": MockSignal(ticker="MSFT", score=-5),
        }
        factors = {"MSFT": MockFactors(ticker="MSFT", composite_score=0.9)}

        alerts = detect_anomalies(signals, factors, {}, {})

        aapl_alerts = [a for a in alerts if a.ticker == "AAPL"]
        msft_alerts = [a for a in alerts if a.ticker == "MSFT"]

        assert len(aapl_alerts) >= 1  # VOLUME_CRASH
        assert len(msft_alerts) >= 1  # TECH_FACTOR_DIVERGENCE
        assert aapl_alerts[0].alert_type == "VOLUME_CRASH"
        assert msft_alerts[0].alert_type == "TECH_FACTOR_DIVERGENCE"
