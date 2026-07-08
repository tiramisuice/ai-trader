"""Simulated portfolio management for paper trading."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from api.trading.models import Position, PortfolioState, TradeOrder, TradeRecord

logger = logging.getLogger(__name__)

STARTING_CAPITAL = 10_000.0


class SimulatedPortfolio:
    """Manages virtual cash and stock positions for one strategy."""

    def __init__(
        self,
        strategy: str,
        cash: float = STARTING_CAPITAL,
        positions: dict[str, Position] | None = None,
        trade_count: int = 0,
        currency: str = "USD",
        starting_capital: float | None = None,
    ) -> None:
        self.strategy = strategy
        self.cash = cash
        self.positions: dict[str, Position] = positions or {}
        self.trade_count = trade_count
        self.currency = currency
        self.starting_capital = starting_capital if starting_capital is not None else cash

    def execute_order(self, order: TradeOrder, price: float) -> TradeRecord | None:
        """Execute a trade order at the given price. Returns a TradeRecord or None if rejected."""
        if price <= 0:
            logger.warning("Rejected order: invalid price %.2f for %s", price, order.ticker)
            return None

        if order.action == "BUY":
            return self._execute_buy(order, price)
        else:
            return self._execute_sell(order, price)

    def _execute_buy(self, order: TradeOrder, price: float) -> TradeRecord | None:
        total_cost = price * order.shares

        if total_cost > self.cash:
            logger.warning(
                "Rejected BUY: %s x%d @ $%.2f = $%.2f exceeds cash $%.2f",
                order.ticker, order.shares, price, total_cost, self.cash,
            )
            return None

        self.cash -= total_cost

        if order.ticker in self.positions:
            pos = self.positions[order.ticker]
            # Update average cost
            old_total = pos.avg_cost * pos.shares
            new_total = old_total + total_cost
            new_shares = pos.shares + order.shares
            pos.avg_cost = new_total / new_shares
            pos.shares = new_shares
            pos.current_price = price
        else:
            self.positions[order.ticker] = Position(
                ticker=order.ticker,
                shares=order.shares,
                avg_cost=price,
                current_price=price,
            )

        self.trade_count += 1
        portfolio_value = self._calc_total_value()

        logger.info(
            "BUY %s x%d @ $%.2f ($%.2f) | cash=$%.2f | total=$%.2f",
            order.ticker, order.shares, price, total_cost, self.cash, portfolio_value,
        )

        return TradeRecord(
            timestamp=datetime.now(timezone.utc),
            strategy=self.strategy,
            action="BUY",
            ticker=order.ticker,
            shares=order.shares,
            price=price,
            total_cost=total_cost,
            reason=order.reason,
            portfolio_value_after=portfolio_value,
        )

    def _execute_sell(self, order: TradeOrder, price: float) -> TradeRecord | None:
        if order.ticker not in self.positions:
            logger.warning("Rejected SELL: no position in %s", order.ticker)
            return None

        pos = self.positions[order.ticker]
        if order.shares > pos.shares:
            logger.warning(
                "Rejected SELL: %s has %d shares, tried to sell %d",
                order.ticker, pos.shares, order.shares,
            )
            return None

        total_proceeds = price * order.shares
        self.cash += total_proceeds

        pos.shares -= order.shares
        pos.current_price = price
        if pos.shares == 0:
            del self.positions[order.ticker]

        self.trade_count += 1
        portfolio_value = self._calc_total_value()

        logger.info(
            "SELL %s x%d @ $%.2f ($%.2f) | cash=$%.2f | total=$%.2f",
            order.ticker, order.shares, price, total_proceeds, self.cash, portfolio_value,
        )

        return TradeRecord(
            timestamp=datetime.now(timezone.utc),
            strategy=self.strategy,
            action="SELL",
            ticker=order.ticker,
            shares=order.shares,
            price=price,
            total_cost=total_proceeds,
            reason=order.reason,
            portfolio_value_after=portfolio_value,
        )

    @property
    def total_value(self) -> float:
        return self._calc_total_value()

    @property
    def total_return_pct(self) -> float:
        tv = self._calc_total_value()
        return round(((tv - self.starting_capital) / self.starting_capital) * 100, 2)

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update current prices for all held positions."""
        for ticker, pos in self.positions.items():
            if ticker in prices:
                pos.current_price = prices[ticker]

    def _calc_total_value(self) -> float:
        positions_value = sum(
            pos.shares * pos.current_price for pos in self.positions.values()
        )
        return round(self.cash + positions_value, 2)

    def get_state(self) -> PortfolioState:
        """Get the current portfolio state as a Pydantic model."""
        total_value = self._calc_total_value()
        market = "tw" if self.currency == "TWD" else "us"
        return PortfolioState(
            strategy=self.strategy,
            cash=round(self.cash, 2),
            positions=dict(self.positions),
            total_value=total_value,
            total_return_pct=round(
                ((total_value - self.starting_capital) / self.starting_capital) * 100, 2
            ),
            trade_count=self.trade_count,
            market=market,
            currency=self.currency,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for persistence."""
        return {
            "strategy": self.strategy,
            "cash": self.cash,
            "positions": {
                ticker: pos.model_dump() for ticker, pos in self.positions.items()
            },
            "trade_count": self.trade_count,
            "currency": self.currency,
            "starting_capital": self.starting_capital,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimulatedPortfolio:
        """Restore from a serialized dict."""
        positions = {
            ticker: Position.model_validate(pos_data)
            for ticker, pos_data in data.get("positions", {}).items()
        }
        currency = data.get("currency", "USD")
        default_capital = STARTING_CAPITAL if currency == "USD" else 300_000.0
        starting_capital = data.get("starting_capital", default_capital)
        return cls(
            strategy=data["strategy"],
            cash=data.get("cash", default_capital),
            positions=positions,
            trade_count=data.get("trade_count", 0),
            currency=currency,
            starting_capital=starting_capital,
        )
