import os
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from alpaca.trading.enums import OrderSide

from graywind_strategy.pipeline import TradeDecision
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
import live_loop
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
          open_positions=None, trading_client=None, pdt_throttle=None, decide_return=None,
          drawdown_breaker=None):
    open_positions = {} if open_positions is None else open_positions
    trading_client = MagicMock() if trading_client is None else trading_client
    pdt_throttle = MagicMock() if pdt_throttle is None else pdt_throttle
    drawdown_breaker = MagicMock() if drawdown_breaker is None else drawdown_breaker
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
            drawdown_breaker=drawdown_breaker,
        )
    return mock_decide, trading_client, pdt_throttle, open_positions, drawdown_breaker


# 1. A held position whose price crosses the stop or target results in a
# sell order being submitted and removed from open_positions.

def test_price_below_stop_submits_sell_and_removes_position():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    _, trading_client, _, remaining, drawdown_breaker = _call(
        symbol="AAPL", current_price=97.0, open_positions=open_positions,
    )
    trading_client.submit_order.assert_called_once()
    order = trading_client.submit_order.call_args[0][0]
    assert order.symbol == "AAPL"
    assert order.qty == 10
    assert order.side == OrderSide.SELL
    assert "AAPL" not in remaining
    # Minor C: a stop/target exit triggers an immediate drawdown_breaker
    # update, mirroring the backtester's per-exit update -- not deferred to
    # the next cycle's single per-cycle call in main().
    drawdown_breaker.update_equity.assert_called_once_with(10000.0)


def test_price_above_target_submits_sell_and_removes_position():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    _, trading_client, _, remaining, drawdown_breaker = _call(
        symbol="AAPL", current_price=104.0, open_positions=open_positions,
    )
    trading_client.submit_order.assert_called_once()
    order = trading_client.submit_order.call_args[0][0]
    assert order.side == OrderSide.SELL
    assert "AAPL" not in remaining
    drawdown_breaker.update_equity.assert_called_once_with(10000.0)


def test_price_between_stop_and_target_does_not_sell():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    _, trading_client, _, remaining, drawdown_breaker = _call(
        symbol="AAPL", current_price=100.0, open_positions=open_positions,
    )
    trading_client.submit_order.assert_not_called()
    assert "AAPL" in remaining
    # No exit -> no extra drawdown_breaker update from process_symbol.
    drawdown_breaker.update_equity.assert_not_called()


# 2. A same-day-opened position that closes same-day records a day-trade
# via pdt_throttle.record_day_trade; one that closes on a later day does not.

def test_same_day_exit_records_day_trade():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    _, _, pdt_throttle, _, _ = _call(
        symbol="AAPL", current_price=97.0, today=date(2024, 1, 8),
        open_positions=open_positions,
    )
    pdt_throttle.record_day_trade.assert_called_once_with(date(2024, 1, 8))


def test_later_day_exit_does_not_record_day_trade():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    _, _, pdt_throttle, _, _ = _call(
        symbol="AAPL", current_price=97.0, today=date(2024, 1, 9),  # closes the next day
        open_positions=open_positions,
    )
    pdt_throttle.record_day_trade.assert_not_called()


# 3. A symbol with an open (non-exiting) position does NOT get a
# decide_trade call this cycle (the skip-if-holding guard).

def test_holding_non_exiting_position_skips_decide_trade():
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    mock_decide, trading_client, _, remaining, _ = _call(
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
    mock_decide, _, _, _, _ = _call(
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
    mock_decide, _, _, _, _ = _call(
        symbol="AAPL", signal="buy", current_price=104.0,  # crosses target -> sell, then re-eval
        today=date(2024, 1, 8), open_positions=open_positions,
    )
    assert mock_decide.call_args.kwargs["pending_same_day_trades"] == 1  # SPY only


# 4b. Real-decide_trade, real-PDTThrottle end-to-end coverage: the mocked
# tests above only prove the right integer gets passed into decide_trade,
# not that the integer has real consequences on the buy/no-buy outcome. The
# three gates are patched to always pass (same pattern as test_pipeline.py's
# _passing_gates), but decide_trade and PDTThrottle themselves are real.

def _passing_gates():
    return patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: True,
        evaluate_sentiment_gate=lambda **kw: True,
        evaluate_earnings_gate=lambda **kw: True,
    )


def test_pending_same_day_trades_real_decide_trade_blocks_when_reservation_hits_cap():
    # 1 realized day-trade + 2 OTHER same-day-open positions -> 1 + 2 >= 3 ->
    # blocked, even though the realized-only count (1) would allow it.
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))
    open_positions = {
        "SPY": _position(shares=5, stop=400.0, target=420.0, opened_date="2024-01-08"),
        "MSFT": _position(shares=3, stop=300.0, target=320.0, opened_date="2024-01-08"),
    }
    trading_client = MagicMock()
    with _passing_gates():
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=throttle, position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    assert "AAPL" not in open_positions


def test_pending_same_day_trades_real_decide_trade_allows_when_reservation_under_cap():
    # Same realized count (1), but one of the "other" positions was opened
    # on an earlier day, so only 1 counts as pending -> 1 + 1 < 3 -> allowed.
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))
    open_positions = {
        "SPY": _position(shares=5, stop=400.0, target=420.0, opened_date="2024-01-08"),
        "MSFT": _position(shares=3, stop=300.0, target=320.0, opened_date="2024-01-07"),  # earlier day
    }
    trading_client = MagicMock()
    with _passing_gates():
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=throttle, position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=MagicMock(),
        )
    trading_client.submit_order.assert_called_once()
    assert "AAPL" in open_positions


# --- reconcile_positions: reconciles local open_positions against Alpaca's
# real account state at the start of each live-loop cycle (final-review
# Fix 5). Local state is authoritative for stop/target/entry_price (Alpaca's
# position API doesn't expose those); Alpaca is authoritative for WHETHER a
# position exists.

def _fake_broker_position(symbol):
    p = MagicMock()
    p.symbol = symbol
    return p


def test_reconcile_positions_drops_locally_tracked_position_broker_no_longer_reports(capsys):
    # An order accepted locally but later rejected/modified by the broker,
    # or a position manually flattened outside the bot, must not be left
    # dangling in local state forever.
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = []  # broker reports nothing held
    open_positions = {"AAPL": _position()}
    result = live_loop.reconcile_positions(trading_client, open_positions)
    assert "AAPL" not in result
    assert "AAPL" not in open_positions  # mutated in place, same dict returned
    err = capsys.readouterr().err
    assert "AAPL" in err and "WARNING" in err


def test_reconcile_positions_does_not_fabricate_broker_only_position(capsys):
    # A position Alpaca reports that isn't locally tracked must trigger a
    # loud warning but must NOT be fabricated into open_positions -- this
    # bot has no record of that position's real entry_price/stop/target, so
    # guessing values for it would be worse than leaving it unmanaged.
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [_fake_broker_position("SPY")]
    open_positions = {}
    result = live_loop.reconcile_positions(trading_client, open_positions)
    assert "SPY" not in result
    err = capsys.readouterr().err
    assert "SPY" in err and "WARNING" in err


def test_reconcile_positions_leaves_matching_position_completely_unchanged(capsys):
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [_fake_broker_position("AAPL")]
    position = _position()
    open_positions = {"AAPL": position}
    result = live_loop.reconcile_positions(trading_client, open_positions)
    assert result == {"AAPL": position}
    assert result["AAPL"] is position  # same object, not replaced/rebuilt
    err = capsys.readouterr().err
    assert err == ""  # no warning when local and broker state agree


# --- main(): per-symbol exception isolation and guaranteed save_state.
# main() itself is otherwise exercised only by the real dry run (Step 10),
# but this specific property -- one symbol's exception can't silently lose
# confirmed state for the whole cycle -- is exactly the kind of bug that
# only shows up in a rare failure path, so it gets a real test with every
# I/O boundary mocked.

class _FakeBar:
    def __init__(self, price, ts):
        self.timestamp = ts
        self.close = price


def test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account

    def fake_fetch_bars(client, symbol, start, end):
        if symbol == "AAPL":
            raise RuntimeError("transient network error")
        return [_FakeBar(100.0, datetime(2024, 1, 8, 10, 0, tzinfo=ET))]

    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state") as mock_save_state, \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df: df.assign(signal="hold")), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")) as mock_decide:
        result = live_loop.main()

    assert result == 0
    # AAPL's fetch_bars raised -> AAPL never reaches decide_trade, but SPY
    # (processed next) still does -- the exception didn't abort the cycle.
    mock_decide.assert_called_once()
    assert mock_decide.call_args.kwargs["symbol"] == "SPY"
    # save_state still ran despite AAPL's exception, with the real
    # accumulated state (no open positions were opened this cycle since
    # decide_trade was mocked to always hold).
    mock_save_state.assert_called_once()
    saved_state = mock_save_state.call_args[0][0]
    assert saved_state["open_positions"] == {}
    assert saved_state["day_trade_dates"] == []


def test_get_account_exception_leaves_day_and_starting_equity_unchanged():
    # An exception above the per-symbol try/except layer (get_account()
    # itself, before the loop even starts) must not prevent save_state from
    # running -- there's nothing new to persist, so it should safely
    # persist back whatever was already loaded rather than raise
    # NameError/UnboundLocalError on an uninitialized starting_equity.
    #
    # Critically, "day" must ALSO be left unchanged (not stamped with
    # today's date) when no fresh baseline was established -- pairing
    # today's date with yesterday's stale starting_equity would make the
    # next cycle think it already has today's baseline (state["day"] ==
    # today) and skip refetching it, running DrawdownBreaker.start_new_day
    # against the wrong number for the rest of the day.
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.side_effect = RuntimeError("Alpaca API down")

    fake_state = {"day_trade_dates": ["2024-01-05"], "day": "2024-01-05", "starting_equity": 9500.0, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state") as mock_save_state:
        try:
            live_loop.main()
        except RuntimeError:
            pass  # get_account()'s failure is expected to propagate; the point is save_state still ran first

    mock_save_state.assert_called_once()
    saved_state = mock_save_state.call_args[0][0]
    assert saved_state["day"] == "2024-01-05"  # unchanged, NOT stamped with today's date
    assert saved_state["starting_equity"] == 9500.0  # unchanged, fell back to the already-persisted value
    assert saved_state["open_positions"] == {}


def test_successful_equity_read_updates_day_and_starting_equity_normally():
    # Contrast case: when get_account() DOES succeed and a fresh baseline
    # IS established this cycle, "day" and "starting_equity" update
    # normally -- confirms the guard above only suppresses the update on
    # failure, not unconditionally.
    fake_account = MagicMock()
    fake_account.equity = "11000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account

    # state["day"] is a stale prior day, distinct from whatever "today"
    # resolves to at test-run time, so the fresh-equity branch is taken.
    fake_state = {"day_trade_dates": [], "day": "2024-01-05", "starting_equity": 9500.0, "open_positions": {}}

    def fake_fetch_bars(client, symbol, start, end):
        return [_FakeBar(100.0, datetime(2024, 1, 8, 10, 0, tzinfo=ET))]

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state") as mock_save_state, \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df: df.assign(signal="hold")), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")):
        result = live_loop.main()

    assert result == 0
    mock_save_state.assert_called_once()
    saved_state = mock_save_state.call_args[0][0]
    assert saved_state["day"] == datetime.now(ET).date().isoformat()
    assert saved_state["starting_equity"] == 11000.0
