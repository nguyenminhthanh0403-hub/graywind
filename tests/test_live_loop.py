from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from alpaca.trading.enums import OrderSide

from graywind_strategy.pipeline import TradeDecision
from live_loop import is_market_hours, process_symbol

ET = ZoneInfo("America/New_York")


def test_is_market_hours_true_during_regular_session():
    assert is_market_hours(now=datetime(2024, 1, 8, 10, 0, tzinfo=ET)) is True  # Mon 10am


def test_is_market_hours_false_before_open():
    assert is_market_hours(now=datetime(2024, 1, 8, 9, 0, tzinfo=ET)) is False  # Mon 9am


def test_is_market_hours_false_after_close():
    assert is_market_hours(now=datetime(2024, 1, 8, 16, 30, tzinfo=ET)) is False  # Mon 4:30pm


def test_is_market_hours_false_on_weekend():
    assert is_market_hours(now=datetime(2024, 1, 6, 10, 0, tzinfo=ET)) is False  # Saturday


# --- process_symbol: the per-symbol decision core extracted from main() for
# testability. main() itself (real network calls) is not unit-tested here,
# matching this project's standing "integration validation via a real run"
# discipline -- see Step 10's dry run.

def _position(shares=10, stop=98.0, target=103.0, opened_date="2024-01-08"):
    return {"entry_price": 100.0, "shares": shares, "stop": stop, "target": target, "opened_date": opened_date}


def _call(symbol="AAPL", signal="hold", current_price=100.0, today=date(2024, 1, 8),
          open_positions=None, trading_client=None, pdt_throttle=None, decide_return=None):
    open_positions = {} if open_positions is None else open_positions
    trading_client = MagicMock() if trading_client is None else trading_client
    pdt_throttle = MagicMock() if pdt_throttle is None else pdt_throttle
    with patch(
        "live_loop.decide_trade",
        return_value=decide_return or TradeDecision(action="hold", reason="no buy signal"),
    ) as mock_decide:
        process_symbol(
            symbol=symbol, signal=signal, current_price=current_price, today=today,
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=pdt_throttle, position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
        )
    return mock_decide, trading_client, pdt_throttle, open_positions


# 1. A held position whose price crosses the stop or target results in a
# sell order being submitted and removed from open_positions.

def test_price_below_stop_submits_sell_and_removes_position():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    _, trading_client, _, remaining = _call(
        symbol="AAPL", current_price=97.0, open_positions=open_positions,
    )
    trading_client.submit_order.assert_called_once()
    order = trading_client.submit_order.call_args[0][0]
    assert order.symbol == "AAPL"
    assert order.qty == 10
    assert order.side == OrderSide.SELL
    assert "AAPL" not in remaining


def test_price_above_target_submits_sell_and_removes_position():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    _, trading_client, _, remaining = _call(
        symbol="AAPL", current_price=104.0, open_positions=open_positions,
    )
    trading_client.submit_order.assert_called_once()
    order = trading_client.submit_order.call_args[0][0]
    assert order.side == OrderSide.SELL
    assert "AAPL" not in remaining


def test_price_between_stop_and_target_does_not_sell():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    _, trading_client, _, remaining = _call(
        symbol="AAPL", current_price=100.0, open_positions=open_positions,
    )
    trading_client.submit_order.assert_not_called()
    assert "AAPL" in remaining


# 2. A same-day-opened position that closes same-day records a day-trade
# via pdt_throttle.record_day_trade; one that closes on a later day does not.

def test_same_day_exit_records_day_trade():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    _, _, pdt_throttle, _ = _call(
        symbol="AAPL", current_price=97.0, today=date(2024, 1, 8),
        open_positions=open_positions,
    )
    pdt_throttle.record_day_trade.assert_called_once_with(date(2024, 1, 8))


def test_later_day_exit_does_not_record_day_trade():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    _, _, pdt_throttle, _ = _call(
        symbol="AAPL", current_price=97.0, today=date(2024, 1, 9),  # closes the next day
        open_positions=open_positions,
    )
    pdt_throttle.record_day_trade.assert_not_called()


# 3. A symbol with an open (non-exiting) position does NOT get a
# decide_trade call this cycle (the skip-if-holding guard).

def test_holding_non_exiting_position_skips_decide_trade():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    mock_decide, trading_client, _, remaining = _call(
        symbol="AAPL", signal="buy", current_price=100.0,  # between stop and target
        open_positions=open_positions,
    )
    mock_decide.assert_not_called()
    trading_client.submit_order.assert_not_called()
    assert "AAPL" in remaining


# 4. pending_same_day_trades passed to decide_trade correctly reflects
# other symbols' same-day-opened still-open positions, excluding the
# symbol currently being evaluated.

def test_pending_same_day_trades_counts_other_same_day_positions_only():
    open_positions = {
        "SPY": _position(shares=5, stop=400.0, target=420.0, opened_date="2024-01-08"),  # same day: counts
        "MSFT": _position(shares=3, stop=300.0, target=320.0, opened_date="2024-01-07"),  # earlier day: doesn't count
    }
    mock_decide, _, _, _ = _call(
        symbol="AAPL", signal="buy", current_price=150.0, today=date(2024, 1, 8),
        open_positions=open_positions,
    )
    assert mock_decide.call_args.kwargs["pending_same_day_trades"] == 1


def test_pending_same_day_trades_excludes_own_just_deleted_entry():
    # AAPL crosses its target and gets sold+deleted this same cycle, then is
    # re-evaluated for a fresh entry -- its own now-deleted entry must not
    # be double counted alongside SPY's still-open same-day position.
    open_positions = {
        "AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08"),
        "SPY": _position(shares=5, stop=400.0, target=420.0, opened_date="2024-01-08"),
    }
    mock_decide, _, _, _ = _call(
        symbol="AAPL", signal="buy", current_price=104.0,  # crosses target -> sell, then re-eval
        today=date(2024, 1, 8), open_positions=open_positions,
    )
    assert mock_decide.call_args.kwargs["pending_same_day_trades"] == 1  # SPY only
