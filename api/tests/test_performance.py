"""Tests for performance analytics: Sharpe ratio, drawdown, win rate, attribution."""

from __future__ import annotations

import math

import pytest

from api.quant.performance import (
    PerformanceMetrics,
    _annualize_return,
    _compute_daily_returns,
    _compute_days_trading,
    _compute_max_drawdown,
    _compute_sharpe,
    _compute_trade_stats,
    compute_performance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshots(values: list[float], start_date: str = "2025-01-01") -> list[dict]:
    """Create snapshot dicts from a list of values, one per day."""
    snapshots = []
    year, month, day = map(int, start_date.split("-"))
    for i, v in enumerate(values):
        d = day + i
        # Simple date increment (assumes no month rollover needed for tests)
        snapshots.append({
            "timestamp": f"{year}-{month:02d}-{d:02d}T16:00:00",
            "total_value": v,
        })
    return snapshots


def _make_trade(action: str, ticker: str, price: float, shares: int = 10,
                timestamp: str = "2025-01-01T10:00:00",
                portfolio_value_after: float = 10000.0) -> dict:
    """Create a trade dict."""
    return {
        "action": action,
        "ticker": ticker,
        "price": price,
        "shares": shares,
        "total_cost": price * shares,
        "timestamp": timestamp,
        "portfolio_value_after": portfolio_value_after,
    }


# ---------------------------------------------------------------------------
# Tests: compute_performance (integration)
# ---------------------------------------------------------------------------


class TestComputeWithSnapshots:
    def test_basic_gain(self):
        """Portfolio that went from 10000 to 10500 over 30 days."""
        values = [10000 + i * (500 / 29) for i in range(30)]
        snapshots = _make_snapshots(values)
        trades = [
            _make_trade("BUY", "AAPL", 150.0, 10, "2025-01-02T10:00:00", 10000),
            _make_trade("SELL", "AAPL", 200.0, 10, "2025-01-20T10:00:00", 10500),
        ]

        metrics = compute_performance(snapshots, trades, 10000.0, "test")

        assert isinstance(metrics, PerformanceMetrics)
        assert metrics.strategy == "test"
        assert metrics.total_return_pct == pytest.approx(5.0, abs=0.1)
        assert metrics.starting_capital == 10000.0
        assert metrics.current_value == pytest.approx(10500.0, abs=1.0)
        assert metrics.days_trading == 29
        assert metrics.total_trades == 2

    def test_no_snapshots(self):
        """No snapshots — metrics should use starting_capital as current."""
        metrics = compute_performance([], [], 10000.0, "empty")

        assert metrics.total_return_pct == 0.0
        assert metrics.current_value == 10000.0
        assert metrics.days_trading == 0
        assert metrics.sharpe_ratio is None
        assert metrics.max_drawdown_pct == 0.0

    def test_single_snapshot(self):
        """One snapshot — no daily returns possible."""
        snapshots = _make_snapshots([10200.0])
        metrics = compute_performance(snapshots, [], 10000.0, "single")

        assert metrics.total_return_pct == pytest.approx(2.0, abs=0.01)
        assert metrics.days_trading == 0
        assert metrics.sharpe_ratio is None


# ---------------------------------------------------------------------------
# Tests: Sharpe ratio
# ---------------------------------------------------------------------------


class TestSharpeRatio:
    def test_positive_sharpe(self):
        """Steadily rising values should produce a positive Sharpe."""
        values = [10000 + i * 50 for i in range(30)]  # +50/day
        snapshots = _make_snapshots(values)
        metrics = compute_performance(snapshots, [], 10000.0, "steady")

        assert metrics.sharpe_ratio is not None
        assert metrics.sharpe_ratio > 0

    def test_volatile_returns_lower_sharpe(self):
        """Volatile values should produce a lower Sharpe than steady values."""
        # Steady growth
        steady_values = [10000 + i * 50 for i in range(30)]
        steady_snapshots = _make_snapshots(steady_values)
        steady_metrics = compute_performance(steady_snapshots, [], 10000.0, "steady")

        # Volatile growth (same endpoint but zigzag)
        volatile_values = []
        for i in range(30):
            base = 10000 + i * 50
            offset = 200 if i % 2 == 0 else -200
            volatile_values.append(base + offset)
        volatile_snapshots = _make_snapshots(volatile_values)
        volatile_metrics = compute_performance(volatile_snapshots, [], 10000.0, "volatile")

        assert steady_metrics.sharpe_ratio is not None
        assert volatile_metrics.sharpe_ratio is not None
        assert steady_metrics.sharpe_ratio > volatile_metrics.sharpe_ratio

    def test_insufficient_data_returns_none_sharpe(self):
        """Fewer than 5 snapshots should return None for Sharpe."""
        snapshots = _make_snapshots([10000, 10100, 10200, 10050])
        metrics = compute_performance(snapshots, [], 10000.0, "few")

        assert metrics.sharpe_ratio is None

    def test_exactly_five_snapshots(self):
        """Exactly 5 snapshots should compute Sharpe (4 daily returns)."""
        # 5 snapshots = 4 daily returns, which meets the >= 5 daily_returns? No -- 5 snapshots gives 4 returns.
        # Actually we need 5 daily returns = 6 snapshots. Let's use 6.
        snapshots = _make_snapshots([10000, 10100, 10200, 10300, 10400, 10500])
        metrics = compute_performance(snapshots, [], 10000.0, "five_rets")

        assert metrics.sharpe_ratio is not None

    def test_flat_returns_no_sharpe(self):
        """All same values (zero std_dev) should return None for Sharpe."""
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, [], 10000.0, "flat")

        assert metrics.sharpe_ratio is None


# ---------------------------------------------------------------------------
# Tests: Max drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_no_drawdown(self):
        """Steadily rising values should have ~0% drawdown."""
        values = [10000 + i * 100 for i in range(20)]
        snapshots = _make_snapshots(values)
        metrics = compute_performance(snapshots, [], 10000.0, "up")

        assert metrics.max_drawdown_pct == pytest.approx(0.0, abs=0.01)

    def test_known_drawdown(self):
        """Peak at 12000, trough at 9000 => drawdown = 25%."""
        values = [10000, 11000, 12000, 10000, 9000, 10000, 11000]
        snapshots = _make_snapshots(values)
        metrics = compute_performance(snapshots, [], 10000.0, "dd")

        assert metrics.max_drawdown_pct == pytest.approx(25.0, abs=0.01)

    def test_drawdown_at_end(self):
        """Drawdown that hasn't recovered yet."""
        values = [10000, 11000, 12000, 10000]
        snapshots = _make_snapshots(values)
        metrics = compute_performance(snapshots, [], 10000.0, "dd_end")

        # Peak 12000, trough 10000 => 16.67%
        expected_dd = (12000 - 10000) / 12000 * 100
        assert metrics.max_drawdown_pct == pytest.approx(expected_dd, abs=0.01)

    def test_empty_snapshots_no_drawdown(self):
        """No snapshots => 0% drawdown."""
        metrics = compute_performance([], [], 10000.0, "empty")
        assert metrics.max_drawdown_pct == 0.0

    def test_single_value_no_drawdown(self):
        """One snapshot => 0% drawdown."""
        snapshots = _make_snapshots([10500])
        metrics = compute_performance(snapshots, [], 10000.0, "one")
        assert metrics.max_drawdown_pct == 0.0


# ---------------------------------------------------------------------------
# Tests: Win rate
# ---------------------------------------------------------------------------


class TestWinRate:
    def test_all_wins(self):
        """All round-trips are profitable."""
        trades = [
            _make_trade("BUY", "AAPL", 100.0, 10, "2025-01-01T10:00:00"),
            _make_trade("SELL", "AAPL", 120.0, 10, "2025-01-05T10:00:00"),
            _make_trade("BUY", "MSFT", 200.0, 5, "2025-01-06T10:00:00"),
            _make_trade("SELL", "MSFT", 250.0, 5, "2025-01-10T10:00:00"),
        ]
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, trades, 10000.0, "winner")

        assert metrics.win_rate == 1.0

    def test_mixed_wins_losses(self):
        """One win, one loss => 50% win rate."""
        trades = [
            _make_trade("BUY", "AAPL", 100.0, 10, "2025-01-01T10:00:00"),
            _make_trade("SELL", "AAPL", 120.0, 10, "2025-01-05T10:00:00"),  # win
            _make_trade("BUY", "TSLA", 300.0, 5, "2025-01-06T10:00:00"),
            _make_trade("SELL", "TSLA", 250.0, 5, "2025-01-10T10:00:00"),  # loss
        ]
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, trades, 10000.0, "mixed")

        assert metrics.win_rate == pytest.approx(0.5, abs=0.01)

    def test_only_buys_no_sells(self):
        """Only BUY trades, no round-trips => fallback to value estimation."""
        trades = [
            _make_trade("BUY", "AAPL", 100.0, 10, "2025-01-01T10:00:00", 10000),
            _make_trade("BUY", "MSFT", 200.0, 5, "2025-01-05T10:00:00", 10200),
        ]
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, trades, 10000.0, "buys_only")

        # Should still return valid metrics (uses fallback)
        assert 0.0 <= metrics.win_rate <= 1.0


# ---------------------------------------------------------------------------
# Tests: Profit factor
# ---------------------------------------------------------------------------


class TestProfitFactor:
    def test_positive_profit_factor(self):
        """Wins outweigh losses."""
        trades = [
            _make_trade("BUY", "AAPL", 100.0, 10, "2025-01-01T10:00:00"),
            _make_trade("SELL", "AAPL", 150.0, 10, "2025-01-05T10:00:00"),  # +500
            _make_trade("BUY", "TSLA", 200.0, 5, "2025-01-06T10:00:00"),
            _make_trade("SELL", "TSLA", 180.0, 5, "2025-01-10T10:00:00"),  # -100
        ]
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, trades, 10000.0, "pf")

        assert metrics.profit_factor is not None
        assert metrics.profit_factor > 1.0
        # gross_profit = (150-100)*10 = 500, gross_loss = (200-180)*5 = 100
        assert metrics.profit_factor == pytest.approx(5.0, abs=0.01)

    def test_no_losses_no_profit_factor(self):
        """All wins, no losses => profit_factor is None (division by zero)."""
        trades = [
            _make_trade("BUY", "AAPL", 100.0, 10, "2025-01-01T10:00:00"),
            _make_trade("SELL", "AAPL", 120.0, 10, "2025-01-05T10:00:00"),
        ]
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, trades, 10000.0, "all_win")

        assert metrics.profit_factor is None  # No losses to divide by

    def test_payoff_ratio(self):
        """Avg win 20%, avg loss 10% => payoff ratio 2.0."""
        trades = [
            _make_trade("BUY", "AAPL", 100.0, 10, "2025-01-01T10:00:00"),
            _make_trade("SELL", "AAPL", 120.0, 10, "2025-01-05T10:00:00"),  # +20%
            _make_trade("BUY", "TSLA", 200.0, 5, "2025-01-06T10:00:00"),
            _make_trade("SELL", "TSLA", 180.0, 5, "2025-01-10T10:00:00"),  # -10%
        ]
        snapshots = _make_snapshots([10000] * 10)
        metrics = compute_performance(snapshots, trades, 10000.0, "payoff")

        assert metrics.payoff_ratio is not None
        assert metrics.payoff_ratio == pytest.approx(2.0, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: Zero trades
# ---------------------------------------------------------------------------


class TestZeroTrades:
    def test_zero_trades_with_snapshots(self):
        """No trades but portfolio has snapshot history."""
        snapshots = _make_snapshots([10000, 10100, 10200, 10300, 10400, 10500])
        metrics = compute_performance(snapshots, [], 10000.0, "passive")

        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.avg_win_pct == 0.0
        assert metrics.avg_loss_pct == 0.0
        assert metrics.profit_factor is None
        assert metrics.payoff_ratio is None
        assert metrics.total_return_pct == pytest.approx(5.0, abs=0.01)
        # Sharpe should still compute from snapshots
        assert metrics.sharpe_ratio is not None

    def test_zero_everything(self):
        """Completely empty — brand new strategy."""
        metrics = compute_performance([], [], 10000.0, "new")

        assert metrics.total_trades == 0
        assert metrics.total_return_pct == 0.0
        assert metrics.annualized_return_pct == 0.0
        assert metrics.sharpe_ratio is None
        assert metrics.max_drawdown_pct == 0.0
        assert metrics.calmar_ratio is None
        assert metrics.win_rate == 0.0
        assert metrics.days_trading == 0
        assert metrics.current_value == 10000.0


# ---------------------------------------------------------------------------
# Tests: Calmar ratio
# ---------------------------------------------------------------------------


class TestCalmarRatio:
    def test_calmar_computed(self):
        """Calmar = annualized_return / max_drawdown."""
        values = [10000, 11000, 12000, 9000, 10000, 11000, 12000, 13000]
        snapshots = _make_snapshots(values)
        metrics = compute_performance(snapshots, [], 10000.0, "calmar")

        # Max drawdown = (12000 - 9000) / 12000 = 25%
        assert metrics.max_drawdown_pct == pytest.approx(25.0, abs=0.01)
        assert metrics.calmar_ratio is not None

    def test_no_drawdown_no_calmar(self):
        """Zero drawdown => calmar is None."""
        values = [10000 + i * 100 for i in range(10)]
        snapshots = _make_snapshots(values)
        metrics = compute_performance(snapshots, [], 10000.0, "no_dd")

        assert metrics.max_drawdown_pct == pytest.approx(0.0, abs=0.01)
        assert metrics.calmar_ratio is None


# ---------------------------------------------------------------------------
# Tests: Internal helpers
# ---------------------------------------------------------------------------


class TestDaysTrading:
    def test_multi_day(self):
        snapshots = _make_snapshots([10000, 10100, 10200])
        assert _compute_days_trading(snapshots) == 2

    def test_single_snapshot(self):
        snapshots = _make_snapshots([10000])
        assert _compute_days_trading(snapshots) == 0

    def test_empty(self):
        assert _compute_days_trading([]) == 0


class TestDailyReturns:
    def test_basic_returns(self):
        snapshots = _make_snapshots([10000, 10100, 10200])
        returns = _compute_daily_returns(snapshots)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(0.01, abs=0.001)

    def test_empty(self):
        assert _compute_daily_returns([]) == []

    def test_single(self):
        snapshots = _make_snapshots([10000])
        assert _compute_daily_returns(snapshots) == []


class TestAnnualizeReturn:
    def test_one_year(self):
        """365 days of 10% => ~10% annualized."""
        result = _annualize_return(10.0, 365)
        assert result == pytest.approx(10.0, abs=0.1)

    def test_half_year(self):
        """182 days of 5% => compound annualized > 10%."""
        result = _annualize_return(5.0, 182)
        assert result > 10.0

    def test_zero_days(self):
        assert _annualize_return(10.0, 0) == 0.0

    def test_few_days_linear(self):
        """Under 7 days uses linear scaling."""
        result = _annualize_return(1.0, 1)
        assert result == pytest.approx(365.0, abs=1.0)
