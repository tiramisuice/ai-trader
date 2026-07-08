"""Performance analytics — Sharpe ratio, drawdown, win rate, attribution."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    strategy: str
    # Returns
    total_return_pct: float
    annualized_return_pct: float
    # Risk
    sharpe_ratio: float | None  # (return - risk_free) / std_dev
    max_drawdown_pct: float  # Worst peak-to-trough decline
    calmar_ratio: float | None  # annualized_return / max_drawdown
    # Trade stats
    total_trades: int
    win_rate: float  # 0-1
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float | None  # gross_profit / gross_loss
    payoff_ratio: float | None  # avg_win / avg_loss
    # Current state
    days_trading: int
    current_value: float
    starting_capital: float


def compute_performance(
    snapshots: list[dict],  # [{timestamp, total_value}, ...]
    trades: list[dict],  # [{action, ticker, price, total_cost, shares, ...}, ...]
    starting_capital: float,
    strategy: str,
) -> PerformanceMetrics:
    """Compute comprehensive performance metrics from trading history.

    Args:
        snapshots: Chronologically ordered list of portfolio value snapshots.
            Each dict must have 'timestamp' (str) and 'total_value' (float).
        trades: List of trade records (dicts with action, ticker, price, shares, total_cost).
        starting_capital: The initial capital for the strategy.
        strategy: The strategy name.

    Returns:
        A PerformanceMetrics dataclass with all computed metrics.
    """
    # --- Basic values ---
    if snapshots:
        current_value = snapshots[-1]["total_value"]
    else:
        current_value = starting_capital

    total_return_pct = ((current_value - starting_capital) / starting_capital) * 100.0 if starting_capital > 0 else 0.0

    # --- Days trading ---
    days_trading = _compute_days_trading(snapshots)

    # --- Annualized return ---
    annualized_return_pct = _annualize_return(total_return_pct, days_trading)

    # --- Daily returns from snapshots ---
    daily_returns = _compute_daily_returns(snapshots)

    # --- Sharpe ratio (need >= 5 snapshots) ---
    sharpe_ratio = _compute_sharpe(daily_returns)

    # --- Max drawdown ---
    max_drawdown_pct = _compute_max_drawdown(snapshots, starting_capital)

    # --- Calmar ratio ---
    calmar_ratio = None
    if max_drawdown_pct > 0 and annualized_return_pct != 0.0:
        calmar_ratio = round(annualized_return_pct / max_drawdown_pct, 4)

    # --- Trade statistics ---
    total_trades = len(trades)
    win_rate, avg_win_pct, avg_loss_pct, profit_factor, payoff_ratio = _compute_trade_stats(trades)

    return PerformanceMetrics(
        strategy=strategy,
        total_return_pct=round(total_return_pct, 4),
        annualized_return_pct=round(annualized_return_pct, 4),
        sharpe_ratio=sharpe_ratio,
        max_drawdown_pct=round(max_drawdown_pct, 4),
        calmar_ratio=calmar_ratio,
        total_trades=total_trades,
        win_rate=round(win_rate, 4),
        avg_win_pct=round(avg_win_pct, 4),
        avg_loss_pct=round(avg_loss_pct, 4),
        profit_factor=profit_factor,
        payoff_ratio=payoff_ratio,
        days_trading=days_trading,
        current_value=round(current_value, 2),
        starting_capital=starting_capital,
    )


# ---------------------------------------------------------------------------
# Internal helper functions
# ---------------------------------------------------------------------------


def _compute_days_trading(snapshots: list[dict]) -> int:
    """Compute the number of days between first and last snapshot."""
    if len(snapshots) < 2:
        return 0
    try:
        first_ts = snapshots[0]["timestamp"]
        last_ts = snapshots[-1]["timestamp"]
        # Parse ISO strings or datetime objects
        if isinstance(first_ts, str):
            first_dt = datetime.fromisoformat(first_ts)
        else:
            first_dt = first_ts
        if isinstance(last_ts, str):
            last_dt = datetime.fromisoformat(last_ts)
        else:
            last_dt = last_ts
        return max((last_dt - first_dt).days, 0)
    except Exception:
        logger.warning("Could not parse snapshot timestamps for days_trading")
        return 0


def _annualize_return(total_return_pct: float, days_trading: int) -> float:
    """Annualize the total return percentage.

    Uses compound annualization: (1 + r)^(365/days) - 1
    Falls back to simple scaling if days < 7.
    """
    if days_trading < 1:
        return 0.0
    r = total_return_pct / 100.0
    if days_trading < 7:
        # Too few days for meaningful compound annualization; scale linearly
        return (r * 365.0 / days_trading) * 100.0
    try:
        annualized = ((1.0 + r) ** (365.0 / days_trading) - 1.0) * 100.0
        return annualized
    except (OverflowError, ValueError):
        return 0.0


def _compute_daily_returns(snapshots: list[dict]) -> list[float]:
    """Compute daily returns from sequential snapshots."""
    if len(snapshots) < 2:
        return []
    returns = []
    for i in range(1, len(snapshots)):
        prev_val = snapshots[i - 1]["total_value"]
        curr_val = snapshots[i]["total_value"]
        if prev_val > 0:
            returns.append((curr_val - prev_val) / prev_val)
    return returns


def _compute_sharpe(daily_returns: list[float]) -> float | None:
    """Compute annualized Sharpe ratio from daily returns.

    Risk-free rate: ~0.01% daily (approximately 4% annual).
    Requires at least 5 data points.
    """
    if len(daily_returns) < 5:
        return None

    risk_free_daily = 0.0001  # ~4% annual
    excess_returns = [r - risk_free_daily for r in daily_returns]

    n = len(excess_returns)
    mean_excess = sum(excess_returns) / n
    variance = sum((r - mean_excess) ** 2 for r in excess_returns) / (n - 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0

    if std_dev == 0:
        return None

    sharpe = (mean_excess / std_dev) * math.sqrt(252)
    return round(sharpe, 4)


def _compute_max_drawdown(snapshots: list[dict], starting_capital: float) -> float:
    """Compute the maximum peak-to-trough drawdown as a percentage.

    Tracks the running peak and measures the worst decline from that peak.
    """
    if not snapshots:
        return 0.0

    values = [s["total_value"] for s in snapshots]
    peak = values[0]
    max_dd = 0.0

    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > max_dd:
                max_dd = dd

    return max_dd


def _compute_trade_stats(
    trades: list[dict],
) -> tuple[float, float, float, float | None, float | None]:
    """Compute win rate, avg win/loss, profit factor, payoff ratio.

    Pairs BUY/SELL trades on the same ticker to form round-trips.
    If there are no completed round-trips, estimates from position P&L
    using portfolio_value_after changes.

    Returns:
        (win_rate, avg_win_pct, avg_loss_pct, profit_factor, payoff_ratio)
    """
    if not trades:
        return 0.0, 0.0, 0.0, None, None

    # Build round-trip pairs: match BUY -> SELL for each ticker
    # Track open positions per ticker (FIFO)
    open_buys: dict[str, list[dict]] = {}  # ticker -> list of buy trades
    round_trip_returns: list[float] = []  # percentage return per round trip
    gross_profit = 0.0
    gross_loss = 0.0

    # Sort trades chronologically (they may come in any order)
    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", ""))

    for trade in sorted_trades:
        action = trade.get("action", "").upper()
        ticker = trade.get("ticker", "")
        price = trade.get("price", 0.0)
        shares = trade.get("shares", 0)

        if action == "BUY":
            if ticker not in open_buys:
                open_buys[ticker] = []
            open_buys[ticker].append(trade)

        elif action == "SELL" and ticker in open_buys and open_buys[ticker]:
            # Match against oldest open buy (FIFO)
            buy_trade = open_buys[ticker][0]
            buy_price = buy_trade.get("price", 0.0)

            if buy_price > 0:
                pnl_pct = ((price - buy_price) / buy_price) * 100.0
                round_trip_returns.append(pnl_pct)

                pnl_dollar = (price - buy_price) * shares
                if pnl_dollar >= 0:
                    gross_profit += pnl_dollar
                else:
                    gross_loss += abs(pnl_dollar)

            # Remove the matched buy (consume shares)
            buy_shares = buy_trade.get("shares", 0)
            if shares >= buy_shares:
                open_buys[ticker].pop(0)
                if not open_buys[ticker]:
                    del open_buys[ticker]
            # If partial sell, we leave the buy for remaining shares
            # (simplified: we treat partial sells as full round-trip for the matched portion)

    # If no round trips, try to estimate from portfolio_value_after
    if not round_trip_returns:
        return _estimate_from_value_changes(trades)

    # Compute stats from round trips
    wins = [r for r in round_trip_returns if r > 0]
    losses = [r for r in round_trip_returns if r <= 0]

    win_rate = len(wins) / len(round_trip_returns) if round_trip_returns else 0.0
    avg_win_pct = sum(wins) / len(wins) if wins else 0.0
    avg_loss_pct = sum(abs(r) for r in losses) / len(losses) if losses else 0.0

    profit_factor = None
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)

    payoff_ratio = None
    if avg_loss_pct > 0:
        payoff_ratio = round(avg_win_pct / avg_loss_pct, 4)

    return win_rate, avg_win_pct, avg_loss_pct, profit_factor, payoff_ratio


def _estimate_from_value_changes(
    trades: list[dict],
) -> tuple[float, float, float, float | None, float | None]:
    """Fallback: estimate win/loss from portfolio_value_after changes between trades."""
    if len(trades) < 2:
        return 0.0, 0.0, 0.0, None, None

    sorted_trades = sorted(trades, key=lambda t: t.get("timestamp", ""))
    changes: list[float] = []

    for i in range(1, len(sorted_trades)):
        prev_val = sorted_trades[i - 1].get("portfolio_value_after", 0)
        curr_val = sorted_trades[i].get("portfolio_value_after", 0)
        if prev_val > 0:
            changes.append(((curr_val - prev_val) / prev_val) * 100.0)

    if not changes:
        return 0.0, 0.0, 0.0, None, None

    wins = [c for c in changes if c > 0]
    losses = [c for c in changes if c <= 0]

    win_rate = len(wins) / len(changes) if changes else 0.0
    avg_win_pct = sum(wins) / len(wins) if wins else 0.0
    avg_loss_pct = sum(abs(c) for c in losses) / len(losses) if losses else 0.0

    payoff_ratio = None
    if avg_loss_pct > 0:
        payoff_ratio = round(avg_win_pct / avg_loss_pct, 4)

    return win_rate, avg_win_pct, avg_loss_pct, None, payoff_ratio
