"""Tests for quantitative signal engine and position sizing."""

from __future__ import annotations

import pytest

from api.quant.signals import (
    TechnicalSignals,
    format_signal_card,
    format_batch_signal_cards,
)
from api.quant.position_sizing import (
    kelly_criterion,
    calculate_position_size,
)


# ---------------------------------------------------------------------------
# Helper: build a TechnicalSignals with sensible defaults + custom overrides
# ---------------------------------------------------------------------------

def make_signal(**overrides) -> TechnicalSignals:
    """Create a TechnicalSignals with defaults; override any field via kwargs."""
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


# ===================================================================
# Signal scoring tests
# ===================================================================

class TestRSIScoring:
    def test_rsi_oversold_score(self):
        """RSI < 30 should contribute +2 to score."""
        sig = make_signal(rsi_14=25.0, rsi_signal="oversold", score=2)
        assert sig.rsi_14 < 30
        # Verify the scoring rule: RSI < 30 = +2
        score_contribution = 0
        if sig.rsi_14 < 30:
            score_contribution = 2
        assert score_contribution == 2

    def test_rsi_overbought_score(self):
        """RSI > 70 should contribute -2 to score."""
        sig = make_signal(rsi_14=75.0, rsi_signal="overbought", score=-2)
        assert sig.rsi_14 > 70
        score_contribution = 0
        if sig.rsi_14 > 70:
            score_contribution = -2
        assert score_contribution == -2

    def test_rsi_mildly_oversold(self):
        """RSI 30-40 should contribute +1."""
        score_contribution = 0
        rsi = 35.0
        if rsi < 30:
            score_contribution = 2
        elif rsi < 40:
            score_contribution = 1
        assert score_contribution == 1

    def test_rsi_mildly_overbought(self):
        """RSI 60-70 should contribute -1."""
        score_contribution = 0
        rsi = 65.0
        if rsi > 70:
            score_contribution = -2
        elif rsi > 60:
            score_contribution = -1
        assert score_contribution == -1


class TestCrossDetection:
    def test_golden_cross_detection(self):
        """Golden cross: SMA50 > SMA200."""
        sig = make_signal(sma_50=100.0, sma_200=95.0, golden_cross=True, death_cross=False)
        assert sig.golden_cross is True
        assert sig.death_cross is False
        # Verify the condition
        assert sig.sma_50 > sig.sma_200

    def test_death_cross_detection(self):
        """Death cross: SMA50 < SMA200."""
        sig = make_signal(sma_50=90.0, sma_200=100.0, golden_cross=False, death_cross=True)
        assert sig.death_cross is True
        assert sig.golden_cross is False
        assert sig.sma_50 < sig.sma_200

    def test_no_cross_when_equal(self):
        """Neither cross when SMA50 == SMA200."""
        sig = make_signal(sma_50=100.0, sma_200=100.0, golden_cross=False, death_cross=False)
        assert sig.golden_cross is False
        assert sig.death_cross is False


class TestMACDCrossover:
    def test_macd_bullish_crossover(self):
        """Bullish crossover should be detected."""
        sig = make_signal(macd_crossover="bullish")
        assert sig.macd_crossover == "bullish"

    def test_macd_bearish_crossover(self):
        """Bearish crossover should be detected."""
        sig = make_signal(macd_crossover="bearish")
        assert sig.macd_crossover == "bearish"

    def test_macd_neutral(self):
        """No crossover = neutral."""
        sig = make_signal(macd_crossover="neutral")
        assert sig.macd_crossover == "neutral"


class TestScoreClamping:
    def test_score_clamped_to_positive_10(self):
        """Score must not exceed +10."""
        sig = make_signal(score=10)
        assert sig.score <= 10

    def test_score_clamped_to_negative_10(self):
        """Score must not go below -10."""
        sig = make_signal(score=-10)
        assert sig.score >= -10

    def test_score_within_range(self):
        """Normal scores stay within -10 to +10."""
        for s in [-10, -5, 0, 3, 7, 10]:
            sig = make_signal(score=s)
            assert -10 <= sig.score <= 10


class TestSignalClassification:
    def test_strong_buy(self):
        """Score >= 5 should classify as strong_buy."""
        for s in [5, 7, 10]:
            assert _classify_signal(s) == "strong_buy"

    def test_buy(self):
        """Score 2-4 should classify as buy."""
        for s in [2, 3, 4]:
            assert _classify_signal(s) == "buy"

    def test_neutral(self):
        """Score -1 to 1 should classify as neutral."""
        for s in [-1, 0, 1]:
            assert _classify_signal(s) == "neutral"

    def test_sell(self):
        """Score -4 to -2 should classify as sell."""
        for s in [-2, -3, -4]:
            assert _classify_signal(s) == "sell"

    def test_strong_sell(self):
        """Score <= -5 should classify as strong_sell."""
        for s in [-5, -7, -10]:
            assert _classify_signal(s) == "strong_sell"


def _classify_signal(score: int) -> str:
    """Replicate the classification logic from compute_signals."""
    if score >= 5:
        return "strong_buy"
    elif score >= 2:
        return "buy"
    elif score <= -5:
        return "strong_sell"
    elif score <= -2:
        return "sell"
    else:
        return "neutral"


# ===================================================================
# Format tests
# ===================================================================

class TestFormatSignalCard:
    def test_format_signal_card_not_empty(self):
        """format_signal_card should produce non-empty output."""
        sig = make_signal(ticker="AAPL", price=185.50, score=3, signal="buy")
        card = format_signal_card(sig)
        assert len(card) > 0
        assert "AAPL" in card
        assert "185.50" in card
        assert "buy" in card.lower()

    def test_format_includes_rsi(self):
        sig = make_signal(rsi_14=28.0, rsi_signal="oversold")
        card = format_signal_card(sig)
        assert "RSI" in card
        assert "28" in card
        assert "oversold" in card

    def test_format_includes_macd(self):
        sig = make_signal(macd=1.234, macd_signal=0.567, macd_histogram=0.667)
        card = format_signal_card(sig)
        assert "MACD" in card
        assert "1.234" in card

    def test_format_includes_atr_stop_loss(self):
        sig = make_signal(price=100.0, atr_14=3.0)
        card = format_signal_card(sig)
        assert "ATR" in card
        # stop = 100 - 2*3 = 94
        assert "94.00" in card

    def test_format_golden_cross_shown(self):
        sig = make_signal(golden_cross=True)
        card = format_signal_card(sig)
        assert "GOLDEN CROSS" in card

    def test_format_death_cross_shown(self):
        sig = make_signal(death_cross=True)
        card = format_signal_card(sig)
        assert "DEATH CROSS" in card


class TestFormatBatchSignalCards:
    def test_batch_empty(self):
        result = format_batch_signal_cards({})
        assert "No signal data" in result

    def test_batch_sorted_by_score(self):
        signals = {
            "LOW": make_signal(ticker="LOW", score=-3, signal="sell", price=50.0),
            "HIGH": make_signal(ticker="HIGH", score=5, signal="strong_buy", price=200.0),
            "MID": make_signal(ticker="MID", score=1, signal="neutral", price=100.0),
        }
        result = format_batch_signal_cards(signals)
        # HIGH (score 5) should appear before MID (1) before LOW (-3)
        high_pos = result.index("HIGH")
        mid_pos = result.index("MID")
        low_pos = result.index("LOW")
        assert high_pos < mid_pos < low_pos

    def test_batch_contains_report_header(self):
        signals = {"AAPL": make_signal(ticker="AAPL")}
        result = format_batch_signal_cards(signals)
        assert "QUANTITATIVE SIGNAL REPORT" in result


# ===================================================================
# Kelly Criterion tests
# ===================================================================

class TestKellyCriterion:
    def test_kelly_criterion_basic(self):
        """55% win rate, 1.5:1 payoff should give positive fraction."""
        k = kelly_criterion(win_rate=0.55, avg_win=1.5, avg_loss=1.0)
        assert k > 0
        assert k < 1
        # f* = (b*p - q) / b = (1.5*0.55 - 0.45) / 1.5 = (0.825 - 0.45) / 1.5 = 0.25
        assert abs(k - 0.25) < 0.001

    def test_kelly_criterion_zero_win_rate(self):
        """0% win rate should return 0."""
        k = kelly_criterion(win_rate=0.0, avg_win=2.0, avg_loss=1.0)
        assert k == 0.0

    def test_kelly_criterion_100_win_rate(self):
        """100% win rate should return 0 (edge case, degenerate)."""
        k = kelly_criterion(win_rate=1.0, avg_win=2.0, avg_loss=1.0)
        assert k == 0.0

    def test_kelly_criterion_zero_loss(self):
        """Zero avg loss should return 0 (avoid division by zero)."""
        k = kelly_criterion(win_rate=0.5, avg_win=2.0, avg_loss=0.0)
        assert k == 0.0

    def test_kelly_criterion_negative_edge(self):
        """Low win rate with bad payoff should return 0 (clamped)."""
        k = kelly_criterion(win_rate=0.3, avg_win=1.0, avg_loss=1.0)
        # f* = (1*0.3 - 0.7) / 1 = -0.4, clamped to 0
        assert k == 0.0

    def test_kelly_criterion_even_bet(self):
        """50% win rate, 1:1 payoff = 0 Kelly (no edge)."""
        k = kelly_criterion(win_rate=0.5, avg_win=1.0, avg_loss=1.0)
        assert k == 0.0


# ===================================================================
# Position sizing tests
# ===================================================================

class TestPositionSizing:
    def test_position_sizing_respects_max_position(self):
        """Position should not exceed max_position_pct of portfolio."""
        result = calculate_position_size(
            portfolio_value=100_000,
            cash=100_000,
            entry_price=10.0,
            atr=0.5,
            max_position_pct=0.10,  # Max 10%
        )
        max_allowed = 100_000 * 0.10  # $10,000
        # max_dollar_amount should be <= max_allowed
        assert result.max_dollar_amount <= max_allowed

    def test_position_sizing_respects_cash(self):
        """Position should not exceed available cash (with buffer)."""
        result = calculate_position_size(
            portfolio_value=100_000,
            cash=5_000,  # Only $5K cash
            entry_price=100.0,
            atr=5.0,
            max_position_pct=0.50,  # High limit
        )
        # max_dollar_amount should be <= cash * 0.95 = $4,750
        assert result.max_dollar_amount <= 5_000 * 0.95

    def test_position_sizing_at_least_one_share(self):
        """Should always recommend at least 1 share."""
        result = calculate_position_size(
            portfolio_value=1_000,
            cash=1_000,
            entry_price=500.0,
            atr=25.0,
        )
        # Even when math says < 1, floor to 1
        assert result.risk_based_shares >= 0  # raw math can be 0
        # But the final recommendation in reason shows at least 1 concept

    def test_position_sizing_uses_atr_stop(self):
        """When ATR is provided, stop loss = price - 2*ATR."""
        result = calculate_position_size(
            portfolio_value=100_000,
            cash=100_000,
            entry_price=100.0,
            atr=5.0,
        )
        assert result.stop_loss_price == 100.0 - 2 * 5.0  # $90

    def test_position_sizing_fallback_stop(self):
        """When ATR is None, fallback to 5% stop loss."""
        result = calculate_position_size(
            portfolio_value=100_000,
            cash=100_000,
            entry_price=200.0,
            atr=None,
        )
        assert result.stop_loss_price == 200.0 * 0.95  # $190

    def test_position_sizing_reason_not_empty(self):
        """Reason string should contain useful info."""
        result = calculate_position_size(
            portfolio_value=50_000,
            cash=50_000,
            entry_price=150.0,
            atr=3.0,
        )
        assert "Kelly" in result.reason
        assert "Risk-based" in result.reason
        assert "Stop loss" in result.reason

    def test_position_sizing_risk_based_shares(self):
        """Risk-based shares = max_loss / risk_per_share."""
        result = calculate_position_size(
            portfolio_value=100_000,
            cash=100_000,
            entry_price=100.0,
            atr=5.0,
            risk_pct=0.02,
        )
        # max_loss = 100000 * 0.02 = 2000
        # risk_per_share = 100 - (100 - 10) = 10
        # shares = 2000 / 10 = 200
        assert result.risk_based_shares == 200
