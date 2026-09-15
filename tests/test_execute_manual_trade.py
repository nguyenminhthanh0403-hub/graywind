from unittest.mock import MagicMock

from scripts.execute_manual_trade import cancel_existing_pending_order


def test_cancel_guard_returns_true_when_no_pending_order():
    trading_client = MagicMock()
    position = {"shares": 10}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_not_called()


def test_cancel_guard_cancels_and_clears_pending_id():
    trading_client = MagicMock()
    position = {"shares": 10, "pending_sell_order_id": "order-1"}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_called_once_with("order-1")
    assert "pending_sell_order_id" not in position


def test_cancel_guard_returns_false_on_cancel_failure_and_leaves_position_untouched():
    trading_client = MagicMock()
    trading_client.cancel_order_by_id.side_effect = RuntimeError("already filled")
    position = {"shares": 10, "pending_sell_order_id": "order-1"}
    assert cancel_existing_pending_order(trading_client, position) is False
    assert position["pending_sell_order_id"] == "order-1"
