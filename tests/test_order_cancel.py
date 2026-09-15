from unittest.mock import MagicMock

from graywind_strategy.order_cancel import cancel_existing_pending_order


def test_cancel_guard_returns_true_when_no_pending_order():
    trading_client = MagicMock()
    position = {"shares": 10}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_not_called()


def test_cancel_guard_cancels_and_clears_pending_id_and_covers():
    trading_client = MagicMock()
    trading_client.get_order_by_id.return_value.filled_qty = "0"
    position = {"shares": 10, "pending_sell_order_id": "order-1", "pending_sell_order_covers": "stop"}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_called_once_with("order-1")
    trading_client.get_order_by_id.assert_called_once_with("order-1")
    assert "pending_sell_order_id" not in position
    assert "pending_sell_order_covers" not in position


def test_cancel_guard_returns_false_on_cancel_failure_and_leaves_position_untouched():
    trading_client = MagicMock()
    trading_client.cancel_order_by_id.side_effect = RuntimeError("already filled")
    position = {"shares": 10, "pending_sell_order_id": "order-1", "pending_sell_order_covers": "target"}
    assert cancel_existing_pending_order(trading_client, position) is False
    assert position["pending_sell_order_id"] == "order-1"
    assert position["pending_sell_order_covers"] == "target"
    trading_client.get_order_by_id.assert_not_called()


def test_cancel_guard_returns_false_when_cancelled_order_had_already_partially_filled():
    # Code-review finding: Alpaca cancels only the REMAINING unfilled
    # quantity -- a successful cancel can still leave shares already sold.
    # Discarding pending_sell_order_id at that point would lose track of
    # those shares (no tier_pools credit, no PDT record, wrong share
    # count). This module has no tier/tier_pools/pdt_throttle context to
    # settle that itself, so it fails closed and leaves the marker in
    # place for live_loop.py's existing terminal-CANCELED-with-partial-fill
    # reconciliation to settle correctly.
    trading_client = MagicMock()
    trading_client.get_order_by_id.return_value.filled_qty = "6"
    position = {"shares": 10, "pending_sell_order_id": "order-1", "pending_sell_order_covers": "stop"}
    assert cancel_existing_pending_order(trading_client, position) is False
    trading_client.cancel_order_by_id.assert_called_once_with("order-1")
    assert position["pending_sell_order_id"] == "order-1"
    assert position["pending_sell_order_covers"] == "stop"


def test_cancel_guard_returns_false_when_fill_status_cannot_be_confirmed():
    trading_client = MagicMock()
    trading_client.get_order_by_id.side_effect = RuntimeError("transient API error")
    position = {"shares": 10, "pending_sell_order_id": "order-1"}
    assert cancel_existing_pending_order(trading_client, position) is False
    assert position["pending_sell_order_id"] == "order-1"
