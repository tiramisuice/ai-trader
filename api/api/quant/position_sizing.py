"""Position sizing formulas — Kelly Criterion + risk-based sizing."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PositionSizeResult:
    ticker: str
    kelly_fraction: float        # Kelly optimal fraction (0-1)
    half_kelly_fraction: float   # Half-Kelly (safer)
    risk_based_shares: int       # Shares based on ATR stop loss
    max_dollar_amount: float     # Max $ to invest in this position
    stop_loss_price: float       # ATR-based stop loss
    reason: str


def kelly_criterion(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Calculate Kelly Criterion optimal bet fraction.

    f* = (bp - q) / b
    where b = avg_win/avg_loss, p = win_rate, q = 1-p

    Returns fraction of bankroll to bet (0 to 1). Negative means don't bet.
    """
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0

    b = avg_win / avg_loss  # Payoff ratio
    p = win_rate
    q = 1 - p

    kelly = (b * p - q) / b
    return max(0.0, min(1.0, kelly))  # Clamp to 0-1


def calculate_position_size(
    portfolio_value: float,
    cash: float,
    entry_price: float,
    atr: float | None,
    risk_pct: float = 0.02,          # Risk 2% of portfolio per trade
    max_position_pct: float = 0.20,  # Max 20% of portfolio in one stock
    win_rate: float = 0.55,          # Default assumed win rate
    avg_win_loss_ratio: float = 1.5, # Default avg win / avg loss
) -> PositionSizeResult:
    """Calculate how many shares to buy using risk management formulas."""

    # Kelly Criterion
    kelly = kelly_criterion(win_rate, avg_win_loss_ratio, 1.0)
    half_kelly = kelly / 2  # More conservative

    # ATR-based stop loss
    if atr and atr > 0:
        stop_loss = entry_price - 2 * atr
        risk_per_share = entry_price - stop_loss
    else:
        # Fallback: 5% stop loss
        stop_loss = entry_price * 0.95
        risk_per_share = entry_price * 0.05

    # Risk-based position sizing
    # Max loss = portfolio_value * risk_pct
    # Shares = max_loss / risk_per_share
    max_loss = portfolio_value * risk_pct
    risk_based_shares = int(max_loss / risk_per_share) if risk_per_share > 0 else 0

    # Kelly-based dollar amount
    kelly_dollars = portfolio_value * half_kelly

    # Max position constraint
    max_dollars = portfolio_value * max_position_pct

    # Cash constraint
    max_from_cash = cash * 0.95  # Keep 5% buffer

    # Take the minimum of all constraints
    final_dollars = min(kelly_dollars, max_dollars, max_from_cash)
    final_shares = int(final_dollars / entry_price) if entry_price > 0 else 0

    # Also constrained by risk-based shares
    final_shares = min(final_shares, risk_based_shares)
    final_shares = max(1, final_shares)  # At least 1 share

    reason = (
        f"Kelly: {kelly:.1%} (half: {half_kelly:.1%}), "
        f"Risk-based: {risk_based_shares} shares @ {risk_pct:.0%} risk, "
        f"Max position: {max_position_pct:.0%}, "
        f"Stop loss: ${stop_loss:.2f}"
    )

    return PositionSizeResult(
        ticker="",
        kelly_fraction=kelly,
        half_kelly_fraction=half_kelly,
        risk_based_shares=risk_based_shares,
        max_dollar_amount=final_dollars,
        stop_loss_price=stop_loss,
        reason=reason,
    )
