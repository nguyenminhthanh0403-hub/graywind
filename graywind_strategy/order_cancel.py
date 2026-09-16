"""Shared pending-sell-order cancellation guard.

Lives here (not in scripts/execute_manual_trade.py, where it originated)
because live_loop.py needs it too, and scripts/execute_manual_trade.py
already imports SIGNAL_LOOKBACK from live_loop.py -- live_loop.py importing
back from there would be circular. Same fix shape as GateResult's earlier
move out of pipeline.py into its own leaf module.
"""
import sys


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

    A successful cancel can still leave a PARTIAL fill already executed --
    Alpaca cancels only the remaining unfilled quantity, not shares already
    sold. Discarding pending_sell_order_id at that point would silently
    lose track of those already-sold shares (no tier_pools credit, no PDT
    record, position["shares"] left wrong), and this leaf module
    deliberately has no tier/tier_pools/pdt_throttle context to settle that
    itself. So a detected partial fill is treated the same as a cancel
    failure -- fail closed, leave the marker in place -- letting
    live_loop.py's existing per-cycle reconciliation (which already
    special-cases a partial fill on a terminal CANCELED order via
    _settle_sell_fill) do the real settlement next time it checks.
    """
    pending_id = position.get("pending_sell_order_id")
    if not pending_id:
        return True
    try:
        trading_client.cancel_order_by_id(pending_id)
    except Exception as exc:
        print(f"could not cancel existing pending order {pending_id}: {exc}", file=sys.stderr)
        return False
    try:
        order = trading_client.get_order_by_id(pending_id)
    except Exception as exc:
        print(f"cancelled order {pending_id} but could not confirm its fill status ({exc}); "
              "leaving it tracked for next cycle's reconciliation", file=sys.stderr)
        return False
    if order is not None and float(order.filled_qty or 0) > 0:
        print(f"cancelled order {pending_id} had already partially filled "
              f"({order.filled_qty} shares); leaving it tracked for next cycle's "
              "reconciliation instead of discarding the fill", file=sys.stderr)
        return False
    position.pop("pending_sell_order_id", None)
    position.pop("pending_sell_order_covers", None)
    return True
