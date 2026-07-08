"""Transaction cost models — commission, transaction tax, and slippage.

Without these the simulation fills at the raw quote, which made high-turnover
strategies look profitable when real-world fees would have consumed the entire
return (tw_quant's estimated fees were ~35% of capital over three months).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCosts:
    commission: float
    tax: float
    slippage: float

    @property
    def total(self) -> float:
        return self.commission + self.tax + self.slippage


@dataclass(frozen=True)
class CostModel:
    """Per-market fee schedule. All rates are fractions of gross trade value."""

    commission_rate: float  # charged on both buys and sells
    min_commission: float   # floor per trade (0 = no minimum)
    sell_tax_rate: float    # charged on sells only (TW securities tax / US SEC fee)
    slippage_rate: float    # execution-quality haircut, both directions

    def for_trade(self, action: str, shares: int, price: float) -> TradeCosts:
        gross = shares * price
        commission = gross * self.commission_rate
        if self.commission_rate > 0 and commission < self.min_commission:
            commission = self.min_commission
        tax = gross * self.sell_tax_rate if action == "SELL" else 0.0
        slippage = gross * self.slippage_rate
        return TradeCosts(
            commission=round(commission, 2),
            tax=round(tax, 2),
            slippage=round(slippage, 2),
        )


# US: commission-free brokerage; SEC fee on sells ($27.80 per $1M); 5 bps slippage
US_COST_MODEL = CostModel(
    commission_rate=0.0,
    min_commission=0.0,
    sell_tax_rate=0.0000278,
    slippage_rate=0.0005,
)

# TW: 0.1425% commission each way (NT$20 minimum), 0.3% securities transaction
# tax on sells, 5 bps slippage
TW_COST_MODEL = CostModel(
    commission_rate=0.001425,
    min_commission=20.0,
    sell_tax_rate=0.003,
    slippage_rate=0.0005,
)

# For tests / hypothetical frictionless comparisons
ZERO_COST_MODEL = CostModel(
    commission_rate=0.0,
    min_commission=0.0,
    sell_tax_rate=0.0,
    slippage_rate=0.0,
)


def cost_model_for_currency(currency: str) -> CostModel:
    return TW_COST_MODEL if currency == "TWD" else US_COST_MODEL
