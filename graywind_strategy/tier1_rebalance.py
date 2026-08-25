"""Pure sizing/drift logic for tier 1's monthly buy-and-hold rebalance --
no I/O, no Alpaca calls (docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md).
live_loop.py's run_tier1_rebalance() is the I/O wrapper that fetches
current holdings/prices and submits whatever orders this returns.
"""
from dataclasses import dataclass

from graywind_strategy.risk.position_sizing import QTY_DECIMALS

DRIFT_THRESHOLD = 0.05


@dataclass
class RebalanceOrder:
    symbol: str
    side: str  # "buy" | "sell"
    qty: float


def compute_rebalance_orders(tier1_equity, current_holdings, current_prices, target_weights,
                              drift_threshold=DRIFT_THRESHOLD):
    orders = []
    for symbol, weight in target_weights.items():
        if symbol not in current_prices:
            continue
        price = current_prices[symbol]
        target_value = tier1_equity * weight
        current_value = current_holdings.get(symbol, 0.0) * price
        drift = (current_value - target_value) / tier1_equity
        if drift > drift_threshold:
            qty = round((current_value - target_value) / price, QTY_DECIMALS)
            orders.append(RebalanceOrder(symbol=symbol, side="sell", qty=qty))
        elif drift < -drift_threshold:
            qty = round((target_value - current_value) / price, QTY_DECIMALS)
            orders.append(RebalanceOrder(symbol=symbol, side="buy", qty=qty))
    return orders


def should_rebalance_this_month(last_rebalance_month, today):
    return last_rebalance_month != today.strftime("%Y-%m")
