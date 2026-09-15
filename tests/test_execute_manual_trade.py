from datetime import date
from unittest.mock import MagicMock, patch

from alpaca.trading.enums import OrderClass, OrderSide
from alpaca.trading.requests import LimitOrderRequest, StopOrderRequest

from scripts.execute_manual_trade import (
    cancel_existing_pending_order, handle_buy_more, handle_close_or_sell_partial,
    handle_set_stop_target,
)


def test_cancel_guard_returns_true_when_no_pending_order():
    trading_client = MagicMock()
    position = {"shares": 10}
    assert cancel_existing_pending_order(trading_client, position) is True
    trading_client.cancel_order_by_id.assert_not_called()


def test_cancel_guard_cancels_and_clears_pending_id():
    trading_client = MagicMock()
    trading_client.get_order_by_id.return_value.filled_qty = "0"
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
    trading_client.get_order_by_id.return_value.filled_qty = "0"
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


def test_buy_more_rejects_without_qty():
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", None, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "positive --qty" in result["reason"]


def test_buy_more_rejects_when_no_local_position():
    trading_client = MagicMock()
    state = {"open_positions": {}, "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", 5.0, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "no locally tracked open position" in result["reason"]


def test_buy_more_rejects_when_symbol_has_no_tier(monkeypatch):
    monkeypatch.setitem(__import__("graywind_strategy.tier_config", fromlist=["SYMBOL_TIER"]).SYMBOL_TIER, "ZZZZ", None)
    trading_client = MagicMock()
    state = {"open_positions": {"ZZZZ": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {}, "ZZZZ", 5.0, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "no tier" in result["reason"]


def test_buy_more_rejects_when_a_sell_order_is_already_resting():
    # Code-review finding: a resting sell order was sized for the CURRENT
    # share count. Silently growing shares underneath it either leaves new
    # shares unprotected (a single-leg stop/target order) or makes a
    # resting close/sell-partial's qty wrong relative to the new total.
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {
        "shares": 10.0, "entry_price": 100.0, "pending_sell_order_id": "order-1",
    }}, "day": None, "starting_equity": None}
    result = handle_buy_more(
        trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", 5.0, date(2026, 9, 14),
    )
    assert result["status"] == "rejected"
    assert "order-1" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_buy_more_rejects_when_daily_breaker_blocks(monkeypatch):
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "1000.0"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": "2026-09-14", "starting_equity": 2000.0}  # already down 50% today
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=[]):
        result = handle_buy_more(
            trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", 5.0,
            date(2026, 9, 14),
        )
    assert result["status"] == "rejected"
    assert "drawdown breaker" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_buy_more_rejects_when_rolling_breaker_blocks_on_todays_live_equity():
    # Code-review finding: live_loop.py's main() always records TODAY's live
    # equity into the rolling breakers (record_equity) before checking
    # can_open_new_trade() -- handle_buy_more was skipping that, so a rolling
    # drawdown breach that happened today but hasn't been through an
    # automated cycle yet (equity_history.csv still only has prior days)
    # would silently bypass the check. Peak 10,000 seven days ago vs. a live
    # 9,000 today is a 10% drop, past the 7-day/5% rolling limit -- but only
    # detectable if today's real equity actually gets recorded, not just
    # whatever stale history was persisted.
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "9000.0"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    history = [(date(2026, 9, 8), 10000.0)]
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=history):
        result = handle_buy_more(
            trading_client, MagicMock(), state, "state", {2: 1000.0}, "AAPL", 5.0,
            date(2026, 9, 10),
        )
    assert result["status"] == "rejected"
    assert "rolling drawdown breaker" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_buy_more_rejects_when_tier_pool_insufficient():
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "1000.0"
    data_client = MagicMock()
    fake_bar = MagicMock(close=100.0)
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=[]), \
         patch("scripts.execute_manual_trade.fetch_bars", return_value=[fake_bar]):
        result = handle_buy_more(
            trading_client, data_client, state, "state", {2: 50.0}, "AAPL", 5.0,
            date(2026, 9, 14),
        )
    assert result["status"] == "rejected"
    assert "pool has" in result["reason"]
    trading_client.submit_order.assert_not_called()


def test_buy_more_submits_and_updates_state_and_tier_pool():
    trading_client = MagicMock()
    trading_client.get_account.return_value.equity = "1000.0"
    data_client = MagicMock()
    fake_bar = MagicMock(close=100.0)
    state = {"open_positions": {"AAPL": {"shares": 10.0, "entry_price": 100.0}},
             "day": None, "starting_equity": None}
    tier_pools = {2: 1000.0}
    with patch("scripts.execute_manual_trade.state_store.load_equity_history", return_value=[]), \
         patch("scripts.execute_manual_trade.fetch_bars", return_value=[fake_bar]):
        result = handle_buy_more(
            trading_client, data_client, state, "state", tier_pools, "AAPL", 5.0,
            date(2026, 9, 14),
        )
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.symbol == "AAPL" and order.qty == 5.0 and order.side == OrderSide.BUY
    assert state["open_positions"]["AAPL"]["shares"] == 15.0
    # weighted average: (10*100 + 5*100) / 15 == 100.0
    assert state["open_positions"]["AAPL"]["entry_price"] == 100.0
    assert tier_pools[2] == 1000.0 - 5.0 * 100.0


def test_set_stop_target_rejects_when_no_local_position():
    trading_client = MagicMock()
    state = {"open_positions": {}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 90.0, 120.0)
    assert result["status"] == "rejected"


def test_set_stop_target_rejects_when_no_prices_given():
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", None, None)
    assert result["status"] == "rejected"
    assert "stop price, a target price, or both" in result["reason"]


def test_set_stop_target_rejects_transposed_prices_before_canceling_existing_order():
    # Code-review finding: validating AFTER canceling would cancel real
    # protection, then get rejected by Alpaca on submit, leaving the
    # position with no resting order at all. Must reject before touching
    # any existing pending order.
    trading_client = MagicMock()
    state = {"open_positions": {"AAPL": {
        "shares": 10.0, "stop": 90.0, "target": 120.0, "pending_sell_order_id": "order-old",
    }}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 130.0, 95.0)
    assert result["status"] == "rejected"
    assert "must be below target price" in result["reason"]
    trading_client.cancel_order_by_id.assert_not_called()
    trading_client.submit_order.assert_not_called()
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-old"


def test_set_stop_target_both_prices_submits_oco():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-oco-1"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 95.0, 130.0)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert order.order_class == OrderClass.OCO
    assert order.qty == 10.0 and order.side == OrderSide.SELL
    assert state["open_positions"]["AAPL"]["pending_sell_order_id"] == "order-oco-1"
    assert state["open_positions"]["AAPL"]["stop"] == 95.0
    assert state["open_positions"]["AAPL"]["target"] == 130.0


def test_set_stop_target_stop_only_submits_plain_stop_order():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-stop-1"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 95.0, None)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert isinstance(order, StopOrderRequest)
    assert order.stop_price == 95.0
    assert state["open_positions"]["AAPL"]["stop"] == 95.0
    assert state["open_positions"]["AAPL"]["target"] == 120.0  # unchanged


def test_set_stop_target_target_only_submits_plain_limit_order():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-limit-1"
    state = {"open_positions": {"AAPL": {"shares": 10.0, "stop": 90.0, "target": 120.0}}}
    result = handle_set_stop_target(trading_client, state, "AAPL", None, 130.0)
    assert result["status"] == "submitted"
    order = trading_client.submit_order.call_args[0][0]
    assert isinstance(order, LimitOrderRequest) and order.order_class != OrderClass.OCO
    assert order.limit_price == 130.0
    assert state["open_positions"]["AAPL"]["target"] == 130.0


def test_set_stop_target_cancels_existing_pending_order_first():
    trading_client = MagicMock()
    trading_client.submit_order.return_value.id = "order-oco-2"
    trading_client.get_order_by_id.return_value.filled_qty = "0"
    state = {"open_positions": {"AAPL": {
        "shares": 10.0, "stop": 90.0, "target": 120.0, "pending_sell_order_id": "order-old",
    }}}
    result = handle_set_stop_target(trading_client, state, "AAPL", 95.0, 130.0)
    trading_client.cancel_order_by_id.assert_called_once_with("order-old")
    assert result["status"] == "submitted"
