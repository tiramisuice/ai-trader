"""Tests for hard risk management rules (Layer 3)."""

import pytest
from api.quant.risk_rules import RiskManager, RiskCheckResult, RuleViolation, create_risk_manager


@pytest.fixture
def rm():
    """Default RiskManager with standard parameters."""
    return RiskManager()


@pytest.fixture
def sample_positions():
    """Sample portfolio positions."""
    return {
        "AAPL": {"shares": 10, "avg_cost": 150.0, "current_price": 160.0},
        "MSFT": {"shares": 5, "avg_cost": 300.0, "current_price": 310.0},
    }


# --- Buy order tests ---

def test_buy_approved_normal_case(rm, sample_positions):
    """A normal buy that satisfies all rules should be approved."""
    result = rm.check_buy_order(
        ticker="GOOGL",
        shares=5,
        price=140.0,
        cash=50000.0,
        portfolio_value=100000.0,
        current_positions=sample_positions,
        trades_this_cycle=0,
    )
    assert result.approved is True
    assert result.violations == []
    assert result.adjusted_shares is None


def test_buy_blocked_insufficient_cash(rm):
    """Buy should be blocked when there is not enough cash even after reserve."""
    result = rm.check_buy_order(
        ticker="AAPL",
        shares=100,
        price=150.0,
        cash=1000.0,          # Only $1000 cash
        portfolio_value=100000.0,
        current_positions={},
        trades_this_cycle=0,
    )
    assert result.approved is False
    blocked_rules = [v.rule for v in result.violations if v.action == "block_trade"]
    assert "MIN_CASH" in blocked_rules


def test_buy_reduced_for_cash_reserve(rm):
    """Buy should be reduced in size to maintain cash reserve."""
    # portfolio_value=100000 -> min_cash = 5000 -> available = 8000 - 5000 = 3000
    # Wants 30 shares at $150 = $4500, but only $3000 available -> 20 shares
    result = rm.check_buy_order(
        ticker="GOOGL",
        shares=30,
        price=150.0,
        cash=8000.0,
        portfolio_value=100000.0,
        current_positions={},
        trades_this_cycle=0,
    )
    assert result.approved is True
    assert result.adjusted_shares is not None
    assert result.adjusted_shares < 30
    assert result.adjusted_shares == int(3000.0 / 150.0)  # 20
    reduce_violations = [v for v in result.violations if v.action == "reduce_size"]
    assert len(reduce_violations) >= 1


def test_buy_blocked_max_position(rm):
    """Buy should be blocked if it would exceed max position percentage."""
    # Existing position already at 25% of portfolio
    positions = {
        "AAPL": {"shares": 100, "avg_cost": 200.0, "current_price": 250.0},
    }
    # Existing AAPL value = 100 * 250 = $25,000 = 25% of $100,000
    # Buying more would exceed limit
    result = rm.check_buy_order(
        ticker="AAPL",
        shares=10,
        price=250.0,
        cash=50000.0,
        portfolio_value=100000.0,
        current_positions=positions,
        trades_this_cycle=0,
    )
    # Should be blocked or reduced since 25% + more would exceed 25%
    blocked = [v for v in result.violations if v.rule == "MAX_POSITION"]
    assert len(blocked) >= 1


def test_buy_reduced_for_position_limit(rm):
    """Buy should be reduced to stay within max position percentage."""
    # Existing AAPL = 50 * 200 = $10,000 = 10% of $100,000
    # Max position = 25% = $25,000 -> can add $15,000 more = 75 shares at $200
    # Request 100 shares -> should be reduced to 75
    positions = {
        "AAPL": {"shares": 50, "avg_cost": 180.0, "current_price": 200.0},
    }
    result = rm.check_buy_order(
        ticker="AAPL",
        shares=100,
        price=200.0,
        cash=90000.0,
        portfolio_value=100000.0,
        current_positions=positions,
        trades_this_cycle=0,
    )
    assert result.approved is True
    assert result.adjusted_shares is not None
    assert result.adjusted_shares <= 75
    reduce_violations = [v for v in result.violations if v.action == "reduce_size"]
    assert len(reduce_violations) >= 1


def test_buy_blocked_max_positions_count(rm):
    """Buy a new stock should be blocked when already holding max positions."""
    # Create 15 existing positions (the default max)
    positions = {
        f"STOCK{i}": {"shares": 10, "avg_cost": 100.0, "current_price": 100.0}
        for i in range(15)
    }
    result = rm.check_buy_order(
        ticker="NEWSTOCK",
        shares=5,
        price=100.0,
        cash=50000.0,
        portfolio_value=100000.0,
        current_positions=positions,
        trades_this_cycle=0,
    )
    assert result.approved is False
    blocked_rules = [v.rule for v in result.violations if v.action == "block_trade"]
    assert "MAX_POSITIONS" in blocked_rules


def test_buy_blocked_max_trades(rm):
    """Buy should be blocked when max trades per cycle is reached."""
    result = rm.check_buy_order(
        ticker="AAPL",
        shares=5,
        price=150.0,
        cash=50000.0,
        portfolio_value=100000.0,
        current_positions={},
        trades_this_cycle=5,  # Already at max (default=5)
    )
    assert result.approved is False
    blocked_rules = [v.rule for v in result.violations if v.action == "block_trade"]
    assert "MAX_TRADES" in blocked_rules


# --- Portfolio health tests ---

def test_stop_loss_triggered(rm):
    """Stop loss should trigger forced sell when position drops past threshold."""
    positions = {
        "AAPL": {"shares": 10, "avg_cost": 200.0, "current_price": 160.0},  # -20%
    }
    result = rm.check_portfolio_health(
        positions=positions,
        portfolio_value=96000.0,
        starting_capital=100000.0,
    )
    assert result.approved is False
    assert len(result.forced_sells) == 1
    assert result.forced_sells[0]["ticker"] == "AAPL"
    force_sell_violations = [v for v in result.violations if v.rule == "STOP_LOSS"]
    assert len(force_sell_violations) == 1


def test_stop_loss_not_triggered(rm):
    """Stop loss should NOT trigger when loss is within limit."""
    # Default stop_loss_pct = 0.15 (15%), position is only down 10%
    positions = {
        "AAPL": {"shares": 10, "avg_cost": 200.0, "current_price": 180.0},  # -10%
    }
    result = rm.check_portfolio_health(
        positions=positions,
        portfolio_value=98000.0,
        starting_capital=100000.0,
    )
    assert len(result.forced_sells) == 0
    stop_loss_violations = [v for v in result.violations if v.rule == "STOP_LOSS"]
    assert len(stop_loss_violations) == 0


def test_daily_loss_halt(rm):
    """Trading should halt when daily loss exceeds limit."""
    result = rm.check_portfolio_health(
        positions={},
        portfolio_value=93000.0,   # Down 7% from starting capital
        starting_capital=100000.0,
    )
    assert result.approved is False
    halt_violations = [v for v in result.violations if v.rule == "DAILY_LOSS_LIMIT"]
    assert len(halt_violations) == 1
    assert "HALT" in halt_violations[0].message


# --- Strategy-specific tests ---

def test_strategy_specific_risk_managers():
    """Different strategies should produce RiskManagers with different parameters."""
    buffett_rm = create_risk_manager("buffett")
    quant_rm = create_risk_manager("quant")

    # Buffett: concentrated, patient, high cash reserve
    assert buffett_rm.max_position_pct == 0.30
    assert buffett_rm.min_cash_pct == 0.20
    assert buffett_rm.max_positions == 5
    assert buffett_rm.max_trades_per_cycle == 2
    assert buffett_rm.stop_loss_pct == 0.20

    # Quant: diversified, tight stop loss
    assert quant_rm.max_position_pct == 0.15
    assert quant_rm.min_cash_pct == 0.05
    assert quant_rm.max_positions == 15
    assert quant_rm.max_trades_per_cycle == 5
    assert quant_rm.stop_loss_pct == 0.10

    # Unknown strategy should return default
    default_rm = create_risk_manager("unknown_strategy")
    assert default_rm.max_position_pct == 0.25  # default


# --- Report formatting tests ---

def test_format_risk_report(rm):
    """Risk report should format violations clearly."""
    # Test all-clear report
    clear_result = RiskCheckResult(approved=True)
    report = rm.format_risk_report(clear_result)
    assert "ALL CLEAR" in report

    # Test report with violations
    violation_result = RiskCheckResult(
        approved=False,
        violations=[
            RuleViolation(rule="MAX_POSITION", message="AAPL too large", action="block_trade"),
            RuleViolation(rule="STOP_LOSS", message="TSLA down -20%", action="force_sell"),
        ],
        forced_sells=[
            {"ticker": "TSLA", "shares": 10, "reason": "STOP LOSS triggered: down -20.0%"},
        ],
    )
    report = rm.format_risk_report(violation_result)
    assert "RISK MANAGEMENT ALERTS" in report
    assert "MAX_POSITION" in report
    assert "STOP_LOSS" in report
    assert "FORCED SELLS" in report
    assert "TSLA" in report
