from unittest.mock import MagicMock

from alpaca.trading.enums import OrderSide

from scripts.execute_manual_trade import (
    cancel_existing_pending_order, handle_close_or_sell_partial,
)


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


def test_close_rejects_nonpositive_qty_without_touching_pending_order():
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01", "pending_sell_order_id": "order-old",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=0)
    assert result["status"] == "rejected"
    assert "qty must be positive" in result["reason"]
    trading_client.cancel_order_by_id.assert_not_called()
    trading_client.submit_order.assert_not_called()
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-old"


def test_close_rejects_when_no_local_position():
    trading_client = MagicMock()
    state = {"open_positions": {}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "rejected"
    assert "no locally tracked open position" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_close_sells_full_shares_and_sets_pending_id():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-9"
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.symbol == "AAPL" and order.qty == 10.0 and order.side == OrderSide.SELL
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-9"


def test_sell_partial_caps_qty_at_held_shares():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-10"
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=999.0)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.qty == 10.0


def test_close_cancels_existing_pending_order_first():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-11"
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01", "pending_sell_order_id": "order-old",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    trading_client.cancel_order_by_id.assert_called_once_with("order-old")
    assert result["status"] == "submitted"
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-11"


def test_close_rejects_when_cancel_of_existing_order_fails():
    trading_client = MagicMock()
    trading_client.cancel_order_by_id.side_effect = RuntimeError("already filled")
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01", "pending_sell_order_id": "order-old",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "rejected"
    trading_client.submit_order.assert_not_called()
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-old"


def test_close_rejects_when_submit_order_raises():
    trading_client = MagicMock()
    trading_client.submit_order.side_effect = RuntimeError("market closed")
    state = {"open_positions": {"AAPL": {
        "entry_price": 100.0, "shares": 10.0, "stop": 90.0, "target": 120.0,
        "opened_date": "2026-09-01",
    }}}
    result = handle_close_or_sell_partial(trading_client, state, "AAPL", qty=None)
    assert result["status"] == "rejected"
    assert "market closed" in result["reason"]
