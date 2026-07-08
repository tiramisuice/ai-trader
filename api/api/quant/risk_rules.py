"""Hard risk management rules — Python-enforced, LLM cannot override."""

from __future__ import annotations
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class RuleViolation:
    rule: str
    message: str
    action: str  # "block_trade", "force_sell", "reduce_size", "warning"

@dataclass
class RiskCheckResult:
    approved: bool
    violations: list[RuleViolation] = field(default_factory=list)
    adjusted_shares: int | None = None  # If size was reduced
    forced_sells: list[dict] = field(default_factory=list)  # Positions to force-sell

class RiskManager:
    """Enforces hard risk rules that LLM decisions cannot violate."""

    def __init__(
        self,
        max_position_pct: float = 0.25,      # Max 25% of portfolio in one stock
        min_cash_pct: float = 0.05,           # Always keep 5% cash
        max_daily_loss_pct: float = 0.05,     # Stop trading if down 5% in a day
        stop_loss_pct: float = 0.15,          # Force sell if position drops 15%
        max_positions: int = 15,              # Max 15 different stocks
        max_trades_per_cycle: int = 5,        # Max 5 trades per cycle
    ):
        self.max_position_pct = max_position_pct
        self.min_cash_pct = min_cash_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.stop_loss_pct = stop_loss_pct
        self.max_positions = max_positions
        self.max_trades_per_cycle = max_trades_per_cycle

    def check_buy_order(
        self,
        ticker: str,
        shares: int,
        price: float,
        cash: float,
        portfolio_value: float,
        current_positions: dict,  # {ticker: {shares, avg_cost, current_price}}
        trades_this_cycle: int = 0,
    ) -> RiskCheckResult:
        """Check if a BUY order passes all risk rules. Returns approved=True or violations."""
        violations = []
        adjusted_shares = shares

        total_cost = shares * price

        # Rule 1: Enough cash (with minimum cash buffer)
        min_cash = portfolio_value * self.min_cash_pct
        available_cash = cash - min_cash
        if total_cost > available_cash:
            max_affordable = int(available_cash / price) if price > 0 else 0
            if max_affordable <= 0:
                violations.append(RuleViolation(
                    rule="MIN_CASH",
                    message=f"Insufficient cash. Need ${total_cost:.0f} but only ${available_cash:.0f} available (keeping {self.min_cash_pct:.0%} reserve)",
                    action="block_trade",
                ))
            else:
                adjusted_shares = max_affordable
                violations.append(RuleViolation(
                    rule="MIN_CASH",
                    message=f"Reduced from {shares} to {adjusted_shares} shares to maintain cash reserve",
                    action="reduce_size",
                ))

        # Rule 2: Max position size
        existing_value = 0
        if ticker in current_positions:
            pos = current_positions[ticker]
            existing_value = pos.get("shares", 0) * pos.get("current_price", price)
        new_position_value = existing_value + (adjusted_shares * price)
        position_pct = new_position_value / portfolio_value if portfolio_value > 0 else 1.0

        if position_pct > self.max_position_pct:
            max_new_value = (portfolio_value * self.max_position_pct) - existing_value
            max_new_shares = int(max_new_value / price) if price > 0 else 0
            if max_new_shares <= 0:
                violations.append(RuleViolation(
                    rule="MAX_POSITION",
                    message=f"{ticker} would be {position_pct:.0%} of portfolio (max {self.max_position_pct:.0%})",
                    action="block_trade",
                ))
            else:
                adjusted_shares = min(adjusted_shares, max_new_shares)
                violations.append(RuleViolation(
                    rule="MAX_POSITION",
                    message=f"Reduced to {adjusted_shares} shares to stay under {self.max_position_pct:.0%} limit",
                    action="reduce_size",
                ))

        # Rule 3: Max number of positions
        if ticker not in current_positions and len(current_positions) >= self.max_positions:
            violations.append(RuleViolation(
                rule="MAX_POSITIONS",
                message=f"Already holding {len(current_positions)} positions (max {self.max_positions})",
                action="block_trade",
            ))

        # Rule 4: Max trades per cycle
        if trades_this_cycle >= self.max_trades_per_cycle:
            violations.append(RuleViolation(
                rule="MAX_TRADES",
                message=f"Already made {trades_this_cycle} trades this cycle (max {self.max_trades_per_cycle})",
                action="block_trade",
            ))

        # Determine final approval
        blocked = any(v.action == "block_trade" for v in violations)

        return RiskCheckResult(
            approved=not blocked,
            violations=violations,
            adjusted_shares=adjusted_shares if adjusted_shares != shares else None,
        )

    def check_portfolio_health(
        self,
        positions: dict,  # {ticker: {shares, avg_cost, current_price}}
    ) -> RiskCheckResult:
        """Check portfolio health and identify positions that need forced selling."""
        violations = []
        forced_sells = []

        # Rule: Stop loss — force sell any position down more than stop_loss_pct
        for ticker, pos in positions.items():
            avg_cost = pos.get("avg_cost", 0)
            current_price = pos.get("current_price", 0)
            if avg_cost > 0 and current_price > 0:
                loss_pct = (current_price - avg_cost) / avg_cost
                if loss_pct < -self.stop_loss_pct:
                    violations.append(RuleViolation(
                        rule="STOP_LOSS",
                        message=f"{ticker} is down {loss_pct:.1%} (stop loss at -{self.stop_loss_pct:.0%})",
                        action="force_sell",
                    ))
                    forced_sells.append({
                        "ticker": ticker,
                        "shares": pos.get("shares", 0),
                        "reason": f"STOP LOSS triggered: down {loss_pct:.1%} from avg cost ${avg_cost:.2f}",
                    })

        return RiskCheckResult(
            approved=len(forced_sells) == 0,
            violations=violations,
            forced_sells=forced_sells,
        )

    def check_daily_loss(
        self,
        day_start_value: float | None,
        current_value: float,
    ) -> RiskCheckResult:
        """Circuit breaker: halt buying when today's loss exceeds max_daily_loss_pct.

        `day_start_value` is the portfolio value at the start of the trading day
        (e.g. today's first snapshot). None means no baseline yet — approved.
        """
        if not day_start_value or day_start_value <= 0:
            return RiskCheckResult(approved=True)

        intraday_return = (current_value - day_start_value) / day_start_value
        if intraday_return < -self.max_daily_loss_pct:
            return RiskCheckResult(
                approved=False,
                violations=[RuleViolation(
                    rule="DAILY_LOSS_LIMIT",
                    message=(
                        f"Portfolio down {intraday_return:.1%} today "
                        f"(limit: -{self.max_daily_loss_pct:.0%}). Buying halted."
                    ),
                    action="block_trade",
                )],
            )
        return RiskCheckResult(approved=True)

    def format_risk_report(self, result: RiskCheckResult) -> str:
        """Format risk check result for LLM context."""
        if not result.violations:
            return "RISK CHECK: ALL CLEAR ✅"

        lines = ["RISK MANAGEMENT ALERTS:"]
        for v in result.violations:
            icon = {"block_trade": "🚫", "force_sell": "⛔", "reduce_size": "⚠️", "warning": "⚠️"}.get(v.action, "❓")
            lines.append(f"  {icon} [{v.rule}] {v.message}")

        if result.forced_sells:
            lines.append("\nFORCED SELLS (non-negotiable):")
            for fs in result.forced_sells:
                lines.append(f"  ⛔ SELL ALL {fs['ticker']} — {fs['reason']}")

        return "\n".join(lines)


# Strategy-specific risk managers with different parameters
def create_risk_manager(strategy_style: str) -> RiskManager:
    """Create a RiskManager with parameters tuned for the strategy style."""
    configs = {
        "buffett": RiskManager(
            max_position_pct=0.30,    # Buffett concentrates
            min_cash_pct=0.20,        # Always keep 20% cash
            max_daily_loss_pct=0.05,
            stop_loss_pct=0.20,       # Wide stop loss (patient)
            max_positions=5,          # Few positions
            max_trades_per_cycle=2,   # Rarely trades
        ),
        "ark": RiskManager(
            max_position_pct=0.30,    # Concentrated bets
            min_cash_pct=0.05,
            max_daily_loss_pct=0.08,  # Tolerates more drawdown
            stop_loss_pct=0.25,       # Very wide (long-term)
            max_positions=10,
            max_trades_per_cycle=3,
        ),
        "momentum": RiskManager(
            max_position_pct=0.20,
            min_cash_pct=0.05,
            max_daily_loss_pct=0.05,
            stop_loss_pct=0.12,       # Tight stop loss
            max_positions=15,
            max_trades_per_cycle=5,
        ),
        "balanced": RiskManager(
            max_position_pct=0.20,
            min_cash_pct=0.10,        # Conservative cash
            max_daily_loss_pct=0.04,
            stop_loss_pct=0.15,
            max_positions=10,
            max_trades_per_cycle=4,
        ),
        "quant": RiskManager(
            max_position_pct=0.15,    # Diversified
            min_cash_pct=0.05,
            max_daily_loss_pct=0.05,
            stop_loss_pct=0.10,       # Tight stop loss
            max_positions=15,
            max_trades_per_cycle=5,
        ),
    }
    return configs.get(strategy_style, RiskManager())
