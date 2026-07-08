"""Anomaly detection — identifies unusual signal combinations that need attention."""

from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class AnomalyAlert:
    ticker: str
    severity: str  # "critical", "warning", "info"
    alert_type: str
    message: str

def detect_anomalies(
    signals: dict,     # TechnicalSignals
    factors: dict,     # FactorScores
    insider: dict,     # InsiderSignals
    earnings: dict,    # EarningsInsights
) -> list[AnomalyAlert]:
    """Detect unusual patterns that may indicate opportunity or danger."""
    alerts = []

    for ticker in signals:
        sig = signals.get(ticker)
        fac = factors.get(ticker)
        ins = insider.get(ticker)
        earn = earnings.get(ticker)

        if not sig:
            continue

        # 1. Volume spike + negative news = potential crash
        if sig.high_volume and sig.rsi_14 and sig.rsi_14 < 35:
            alerts.append(AnomalyAlert(
                ticker=ticker, severity="warning", alert_type="VOLUME_CRASH",
                message=f"High volume ({sig.volume_ratio:.1f}x avg) with RSI {sig.rsi_14:.0f} — possible capitulation or buying opportunity"
            ))

        # 2. Insider selling + death cross = danger
        if ins and ins.signal == "bearish" and sig.death_cross:
            alerts.append(AnomalyAlert(
                ticker=ticker, severity="critical", alert_type="INSIDER_EXIT",
                message=f"Insider selling + Death Cross — insiders may know something"
            ))

        # 3. Insider buying + oversold = strong buy signal
        if ins and ins.signal == "bullish" and sig.rsi_signal == "oversold":
            alerts.append(AnomalyAlert(
                ticker=ticker, severity="info", alert_type="INSIDER_BUY_DIP",
                message=f"Insider buying while RSI oversold ({sig.rsi_14:.0f}) — strong contrarian buy signal"
            ))

        # 4. Extreme divergence: technicals say sell but factors say buy
        if fac and sig.score <= -3 and fac.composite_score > 0.5:
            alerts.append(AnomalyAlert(
                ticker=ticker, severity="info", alert_type="TECH_FACTOR_DIVERGENCE",
                message=f"Technical score {sig.score:+d} (sell) but factor score {fac.composite_score:.2f} (buy) — value opportunity or value trap?"
            ))

        # 5. Earnings beat + momentum = chase signal
        if earn and earn.sentiment == "positive" and sig.score >= 3:
            alerts.append(AnomalyAlert(
                ticker=ticker, severity="info", alert_type="EARNINGS_MOMENTUM",
                message=f"Positive earnings + strong technical score ({sig.score:+d}) — momentum continuation likely"
            ))

        # 6. Bollinger squeeze (low volatility before potential breakout)
        if sig.bb_upper and sig.bb_lower and sig.atr_14:
            bb_width = (sig.bb_upper - sig.bb_lower) / sig.price
            if bb_width < 0.04:  # Less than 4% band width
                alerts.append(AnomalyAlert(
                    ticker=ticker, severity="info", alert_type="BOLLINGER_SQUEEZE",
                    message=f"Bollinger Bands squeezed ({bb_width:.1%} width) — breakout imminent"
                ))

    # Sort by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: severity_order.get(a.severity, 3))

    return alerts

def format_anomaly_report(alerts: list[AnomalyAlert]) -> str:
    """Format anomaly alerts for LLM prompt."""
    if not alerts:
        return ""

    icons = {"critical": "\U0001f6a8", "warning": "\u26a0\ufe0f", "info": "\U0001f4a1"}
    lines = ["ANOMALY ALERTS:"]
    for a in alerts:
        icon = icons.get(a.severity, "\u2753")
        lines.append(f"  {icon} [{a.alert_type}] {a.ticker}: {a.message}")

    return "\n".join(lines)
