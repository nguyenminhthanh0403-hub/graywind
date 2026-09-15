#!/usr/bin/env python3
"""Executes one manual trade-panel action (close, sell_partial, buy_more,
set_stop_target) against Alpaca, dispatched by manual-trade.yml on behalf
of index.html's position action panel via the manual-trade-trigger
Cloudflare Worker.

Deliberately reuses graywind_strategy/state_store.py's existing schema
rather than inventing new settlement bookkeeping: a sell-side action
(close/sell_partial/set_stop_target) never settles here -- it only submits
the order and records `pending_sell_order_id`, handing settlement (real
fill price, tier_pools credit, PDT recording) to live_loop.py's existing
pending-order machinery (live_loop.py:348-430), identical to how a
stop/target exit settles today. Only buy_more updates state synchronously
here, mirroring process_pending_trades' existing approved-buy path
(live_loop.py:809-839), which assumes a market buy fills at
approximately the fetched price.

Requires ALPACA_API_KEY/ALPACA_API_SECRET in the environment (selected by
manual-trade.yml per --account) -- see .env.example.
"""
import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest, MarketOrderRequest, StopLossRequest, StopOrderRequest,
    TakeProfitRequest,
)

from fetch_alpaca_data import fetch_bars
from graywind_strategy import manual_actions_log, state_store
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker, build_rolling_breakers
from graywind_strategy.tier_config import SYMBOL_TIER

ET = ZoneInfo("America/New_York")


def cancel_existing_pending_order(trading_client, position):
    """A sell-side action must never leave two live orders against the same
    shares. `position` may already carry a `pending_sell_order_id` from an
    earlier stop/target order or a close/sell-partial still awaiting
    next-cycle settlement.

    A cancel failure is treated as "state unknown, do not proceed" rather
    than trying to distinguish a transient API error from "the order
    already filled" -- guessing wrong in the filled case would submit a
    second real sell against shares that are already gone. Fails closed;
    the caller surfaces this as a rejection and the position resolves
    itself on the next live_loop cycle either way.
    """
    pending_id = position.get("pending_sell_order_id")
    if not pending_id:
        return True
    try:
        trading_client.cancel_order_by_id(pending_id)
    except Exception as exc:
        print(f"could not cancel existing pending order {pending_id}: {exc}", file=sys.stderr)
        return False
    position.pop("pending_sell_order_id", None)
    return True


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", required=True, choices=["100k", "small"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument(
        "--action", required=True,
        choices=["close", "sell_partial", "buy_more", "set_stop_target"],
    )
    parser.add_argument("--qty", type=float, default=None)
    parser.add_argument("--stop-price", type=float, default=None)
    parser.add_argument("--target-price", type=float, default=None)
    parser.add_argument("--idempotency-key", required=True)
    return parser.parse_args(argv)


def handle_close_or_sell_partial(trading_client, state, symbol, qty):
    position = state["open_positions"].get(symbol)
    if position is None:
        return {"status": "rejected", "reason": f"{symbol}: no locally tracked open position"}

    if qty is not None and qty <= 0:
        return {"status": "rejected", "reason": f"{symbol}: qty must be positive"}

    sell_qty = position["shares"] if qty is None else min(qty, position["shares"])

    if not cancel_existing_pending_order(trading_client, position):
        return {
            "status": "rejected",
            "reason": f"{symbol}: could not confirm cancellation of an existing pending "
                      "order; try again next cycle",
        }

    order = MarketOrderRequest(
        symbol=symbol, qty=sell_qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
    )
    try:
        submitted = trading_client.submit_order(order)
    except Exception as exc:
        return {"status": "rejected", "reason": f"{symbol}: order submission failed ({exc})"}

    position["pending_sell_order_id"] = str(submitted.id)
    return {
        "status": "submitted",
        "reason": f"{symbol}: sell order {submitted.id} submitted for {sell_qty} shares; "
                  "settles on the next live cycle",
    }


if __name__ == "__main__":
    sys.exit(1)  # placeholder entrypoint; replaced by main() in Task 6
