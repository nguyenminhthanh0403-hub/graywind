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
from datetime import datetime
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
from graywind_strategy.order_cancel import cancel_existing_pending_order
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker, build_rolling_breakers
from graywind_strategy.tier_config import SYMBOL_TIER
from live_loop import SIGNAL_LOOKBACK

ET = ZoneInfo("America/New_York")


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


def handle_buy_more(trading_client, data_client, state, state_dir, tier_pools, symbol, qty, today):
    if qty is None or qty <= 0:
        return {"status": "rejected", "reason": f"{symbol}: buy_more requires a positive --qty"}

    position = state["open_positions"].get(symbol)
    if position is None:
        return {"status": "rejected", "reason": f"{symbol}: no locally tracked open position to add to"}
    if position.get("pending_sell_order_id"):
        # A resting sell order (full close/partial-sell, or a single-leg
        # stop/target order) was sized for the CURRENT share count.
        # Silently growing position["shares"] underneath it would either
        # leave the newly bought shares with no stop/target protection at
        # all (single-leg case) or make a resting close/sell-partial's qty
        # wrong relative to the new total. Refuse instead -- the caller can
        # retry once the resting order settles or is canceled.
        return {
            "status": "rejected",
            "reason": f"{symbol}: a sell order ({position['pending_sell_order_id']}) is already "
                      "resting on this position; cannot buy more until it resolves",
        }

    tier = SYMBOL_TIER.get(symbol)
    if tier is None:
        return {"status": "rejected", "reason": f"{symbol}: no tier in SYMBOL_TIER; refusing to size a buy"}

    account = trading_client.get_account()
    equity = float(account.equity)
    # Same formula main() uses (live_loop.py:955): reuse today's already-
    # established baseline if one exists, otherwise this cycle's equity IS
    # the baseline. Deliberately does not persist this via save_state -- if
    # this runs before the day's first automated cycle, that cycle still
    # establishes its own baseline the same way; a same-day difference of a
    # few minutes' equity drift is an acceptable approximation for a paper
    # account, not a correctness bug.
    starting_equity = state["starting_equity"] if state["day"] == today.isoformat() else equity

    drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    if starting_equity > 0:
        drawdown_breaker.start_new_day(today, starting_equity)
        drawdown_breaker.update_equity(equity)
    else:
        drawdown_breaker.trip()
    if not drawdown_breaker.can_open_new_trade():
        return {"status": "rejected", "reason": f"{symbol}: daily drawdown breaker blocks new buys right now"}

    rolling_breakers = build_rolling_breakers()
    equity_history = state_store.load_equity_history(state_dir=state_dir)
    for breaker in rolling_breakers:
        breaker.load_history(equity_history)
    # Mirrors live_loop.py's main(): record TODAY's live equity before
    # checking can_open_new_trade(), not just whatever history was persisted
    # by the last automated cycle. Without this, a rolling-window breach
    # that happened today but hasn't been through an automated cycle yet
    # (equity_history.csv still only has prior days) would silently let a
    # manual buy-more through a drawdown level main() would have blocked.
    if equity > 0:
        for breaker in rolling_breakers:
            breaker.record_equity(today, equity)
    if not all(b.can_open_new_trade() for b in rolling_breakers):
        return {"status": "rejected", "reason": f"{symbol}: a rolling drawdown breaker blocks new buys right now"}

    now = datetime.now(ET)
    bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
    if not bars:
        return {"status": "rejected", "reason": f"{symbol}: could not fetch a current price"}
    current_price = bars[-1].close
    cost = qty * current_price
    pool_cash = tier_pools.get(tier, 0.0)
    if cost > pool_cash:
        return {
            "status": "rejected",
            "reason": f"{symbol}: tier {tier} pool has ${pool_cash:.2f}, needs ${cost:.2f}",
        }

    order = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
    try:
        trading_client.submit_order(order)
    except Exception as exc:
        return {"status": "rejected", "reason": f"{symbol}: buy order submission failed ({exc})"}

    total_shares = position["shares"] + qty
    position["entry_price"] = (position["entry_price"] * position["shares"] + current_price * qty) / total_shares
    position["shares"] = total_shares
    tier_pools[tier] = pool_cash - cost
    return {"status": "submitted", "reason": f"{symbol}: bought {qty} more shares at ~{current_price}"}


def handle_set_stop_target(trading_client, state, symbol, stop_price, target_price):
    position = state["open_positions"].get(symbol)
    if position is None:
        return {"status": "rejected", "reason": f"{symbol}: no locally tracked open position"}
    if stop_price is None and target_price is None:
        return {"status": "rejected", "reason": f"{symbol}: must supply a stop price, a target price, or both"}
    if stop_price is not None and target_price is not None and stop_price >= target_price:
        # Checked BEFORE canceling any existing resting order below -- a
        # transposed pair would otherwise cancel real protection, then get
        # rejected by Alpaca on submit, leaving the position with no
        # resting order at all until the next retry or the ordinary
        # stop/target check happens to catch it.
        return {
            "status": "rejected",
            "reason": f"{symbol}: stop price ({stop_price}) must be below target price ({target_price})",
        }

    if not cancel_existing_pending_order(trading_client, position):
        return {
            "status": "rejected",
            "reason": f"{symbol}: could not confirm cancellation of an existing pending "
                      "order; try again next cycle",
        }

    shares = position["shares"]
    if stop_price is not None and target_price is not None:
        order = LimitOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            order_class=OrderClass.OCO, limit_price=target_price,
            take_profit=TakeProfitRequest(limit_price=target_price),
            stop_loss=StopLossRequest(stop_price=stop_price),
        )
    elif stop_price is not None:
        order = StopOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            stop_price=stop_price,
        )
    else:
        order = LimitOrderRequest(
            symbol=symbol, qty=shares, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
            limit_price=target_price,
        )

    try:
        submitted = trading_client.submit_order(order)
    except Exception as exc:
        return {"status": "rejected", "reason": f"{symbol}: stop/target order submission failed ({exc})"}

    position["pending_sell_order_id"] = str(submitted.id)
    # Recorded so live_loop.py knows which leg(s) this resting order actually
    # enforces -- a stop-only or target-only order leaves the other leg with
    # no broker-side protection, and live_loop must keep watching it locally
    # instead of treating any pending_sell_order_id as full coverage (see
    # order_cancel.py's docstring precedent for this kind of leaf-level fix).
    if stop_price is not None and target_price is not None:
        position["pending_sell_order_covers"] = "both"
    elif stop_price is not None:
        position["pending_sell_order_covers"] = "stop"
    else:
        position["pending_sell_order_covers"] = "target"
    if stop_price is not None:
        position["stop"] = stop_price
    if target_price is not None:
        position["target"] = target_price
    return {"status": "submitted", "reason": f"{symbol}: stop/target order {submitted.id} resting at Alpaca"}


if __name__ == "__main__":
    sys.exit(1)  # placeholder entrypoint; replaced by main() in Task 6
