import os
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.trading.enums import OrderSide

from graywind_strategy.pipeline import TradeDecision
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
import live_loop
from live_loop import is_market_hours, process_symbol, run_tier1_rebalance

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
          drawdown_breaker=None, equity=10000.0, tier_pools=None):
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
            open_positions=open_positions, equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, tier_pools=tier_pools,
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
        evaluate_macro_gate=lambda **kw: True,
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
            pdt_throttle=throttle, position_sizer=PositionSizer(),
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
            pdt_throttle=throttle, position_sizer=PositionSizer(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=MagicMock(),
        )
    trading_client.submit_order.assert_called_once()
    assert "AAPL" in open_positions


# --- dashboard export collection: process_symbol optionally records what
# happened this cycle into caller-supplied cycle_trades/symbol_statuses,
# defaulting to None (no-op) so every pre-existing call site above is
# unaffected.

def test_process_symbol_records_buy_trade_and_status_when_collectors_passed():
    cycle_trades = []
    symbol_statuses = {}
    with patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
    ):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
        )
    assert cycle_trades == [{
        "timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "buy",
        "qty": 10, "price": 100.0, "reason": "signal=buy",
    }]
    assert symbol_statuses["AAPL"]["action"] == "buy"
    assert symbol_statuses["AAPL"]["position_open"] is True


def test_process_symbol_records_sell_trade_on_stop_exit():
    cycle_trades = []
    symbol_statuses = {}
    open_positions = {"AAPL": _position(stop=98.0, target=103.0)}
    process_symbol(
        symbol="AAPL", signal="hold", current_price=97.0, today=date(2024, 1, 8),
        open_positions=open_positions, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
    )
    sell_trades = [t for t in cycle_trades if t["side"] == "sell"]
    assert sell_trades == [{
        "timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "side": "sell",
        "qty": 10, "price": 97.0, "reason": "stop/target exit",
    }]


def test_process_symbol_records_hold_status_for_already_held_position():
    symbol_statuses = {}
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    process_symbol(
        symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
        open_positions=open_positions, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=[], symbol_statuses=symbol_statuses,
    )
    assert symbol_statuses["AAPL"]["action"] == "hold"
    assert symbol_statuses["AAPL"]["position_open"] is True
    assert symbol_statuses["AAPL"]["shares"] == 10


def test_process_symbol_without_collectors_behaves_exactly_as_before():
    # No cycle_timestamp/cycle_trades/symbol_statuses passed -- must not
    # raise, matching every pre-existing call site in this file.
    trading_client = MagicMock()
    process_symbol(
        symbol="AAPL", signal="hold", current_price=100.0, today=date(2024, 1, 8),
        open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=trading_client, drawdown_breaker=MagicMock(),
    )
    trading_client.submit_order.assert_not_called()


def test_process_symbol_appends_decision_log_row_when_decide_trade_runs():
    decision_rows = []
    with patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="all checks passed", shares=10, stop_price=98.0, target_price=103.0),
    ):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00",
            rsi=45.2, sma_fast=101.0, sma_slow=99.0,
            decision_rows=decision_rows,
        )
    assert decision_rows == [{
        "timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "action": "buy",
        "reason": "all checks passed", "rsi": "45.2", "sma_fast": "101.0", "sma_slow": "99.0",
        "vix": "", "sentiment": "", "days_to_earnings": "", "macro_breaches": "", "sector_gates": "",
    }]


def test_process_symbol_decision_row_includes_gate_values_from_gate_readings():
    from graywind_strategy.gate_result import GateResult

    decision_rows = []
    decision = TradeDecision(
        action="blocked", reason="macro_gate",
        gate_readings=[
            GateResult(passed=True, value=15.0),   # vix
            GateResult(passed=True, value=0.05),   # sentiment
            GateResult(passed=True, value=12),     # earnings (days_to_earnings)
            GateResult(passed=False, value=2),     # macro (breaches) -- blocked here, sector never ran
        ],
    )
    with patch("live_loop.decide_trade", return_value=decision):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="t1", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
            decision_rows=decision_rows,
        )
    row = decision_rows[0]
    assert row["vix"] == "15.0"
    assert row["sentiment"] == "0.05"
    assert row["days_to_earnings"] == "12"
    assert row["macro_breaches"] == "2"
    assert row["sector_gates"] == ""  # never reached -- blocked before the sector gate ran


def test_process_symbol_decision_row_shows_none_sentinel_when_earnings_gate_ran_and_found_no_earnings():
    # I5: evaluate_earnings_gate legitimately returns value=None when it
    # actually ran and found no earnings scheduled -- a real, meaningful
    # reading, distinct from the gate never having run at all (an earlier
    # gate short-circuited first). Both used to collapse to the same blank
    # "" in decision_log.csv; the earnings-ran-with-no-earnings case must
    # now show the "none" sentinel instead.
    from graywind_strategy.gate_result import GateResult

    decision_rows = []
    decision = TradeDecision(
        action="blocked", reason="macro_gate",
        gate_readings=[
            GateResult(passed=True, value=15.0),   # vix
            GateResult(passed=True, value=0.05),   # sentiment
            GateResult(passed=True, value=None),   # earnings -- ran, no earnings scheduled
            GateResult(passed=False, value=2),     # macro -- blocked here, sector never ran
        ],
    )
    with patch("live_loop.decide_trade", return_value=decision):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="t1", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
            decision_rows=decision_rows,
        )
    row = decision_rows[0]
    assert row["days_to_earnings"] == "none"


def test_process_symbol_decision_row_shows_blank_when_earnings_gate_never_ran():
    # Contrast case: earnings never reached (blocked earlier, e.g. by
    # sentiment_gate) must still show blank "", not the "none" sentinel --
    # that sentinel means "ran and found nothing," not "didn't run."
    from graywind_strategy.gate_result import GateResult

    decision_rows = []
    decision = TradeDecision(
        action="blocked", reason="sentiment_gate",
        gate_readings=[
            GateResult(passed=True, value=15.0),    # vix
            GateResult(passed=False, value=-0.5),   # sentiment -- blocked here, earnings never ran
        ],
    )
    with patch("live_loop.decide_trade", return_value=decision):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="t1", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
            decision_rows=decision_rows,
        )
    row = decision_rows[0]
    assert row["days_to_earnings"] == ""


def test_process_symbol_does_not_append_decision_row_when_skipping_via_held_position():
    decision_rows = []
    symbol_statuses = {}
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    process_symbol(
        symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
        open_positions=open_positions, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        cycle_timestamp="t1", symbol_statuses=symbol_statuses, decision_rows=decision_rows,
    )
    # decide_trade is never called for an already-held, non-exiting position
    # (the skip-if-holding guard) -- no row to append for it this cycle.
    assert decision_rows == []


def test_process_symbol_without_decision_rows_does_not_raise():
    # decision_rows defaults to None -- must not raise, matching every
    # pre-existing call site in this file.
    with patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="hold", reason="no buy signal"),
    ):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        )


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
    trading_client.get_all_positions.return_value = [_fake_broker_position("SERV")]
    open_positions = {}
    result = live_loop.reconcile_positions(trading_client, open_positions)
    assert "SERV" not in result
    err = capsys.readouterr().err
    assert "SERV" in err and "WARNING" in err


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
        self.high = price
        self.low = price


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
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")) as mock_decide, \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.write_cycle_export"):
        result = live_loop.main()

    assert result == 0
    # AAPL's fetch_bars raised -> AAPL never reaches decide_trade, but SERV
    # (processed next) still does -- the exception didn't abort the cycle.
    mock_decide.assert_called_once()
    assert mock_decide.call_args.kwargs["symbol"] == "SERV"
    # save_state still ran despite AAPL's exception, with the real
    # accumulated state (no open positions were opened this cycle since
    # decide_trade was mocked to always hold).
    mock_save_state.assert_called_once()
    saved_state = mock_save_state.call_args[0][0]
    assert saved_state["open_positions"] == {}
    assert saved_state["day_trade_dates"] == []


def test_main_threads_graywind_state_dir_env_var_into_every_state_call():
    fake_account = MagicMock()
    fake_account.equity = "2000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []

    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
             "GRAYWIND_STATE_DIR": "state/small",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state) as mock_load_state, \
         patch("live_loop.save_state") as mock_save_state, \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}) as mock_load_tier_pools, \
         patch("live_loop.save_tier_pools") as mock_save_tier_pools, \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}) as mock_load_rebalance, \
         patch("live_loop.save_rebalance_state") as mock_save_rebalance, \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.append_decision_log") as mock_append_decision_log, \
         patch("live_loop.write_cycle_export"):
        result = live_loop.main()

    assert result == 0
    assert mock_load_state.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_state.call_args.kwargs["state_dir"] == "state/small"
    assert mock_load_tier_pools.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_tier_pools.call_args.kwargs["state_dir"] == "state/small"
    assert mock_load_rebalance.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_rebalance.call_args.kwargs["state_dir"] == "state/small"
    assert mock_append_decision_log.call_args.kwargs["state_dir"] == "state/small"


def test_main_defaults_graywind_state_dir_to_state_when_env_var_unset():
    fake_account = MagicMock()
    fake_account.equity = "100000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []

    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }, clear=False), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state) as mock_load_state, \
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.append_decision_log") as mock_append_decision_log, \
         patch("live_loop.write_cycle_export"):
        os.environ.pop("GRAYWIND_STATE_DIR", None)
        result = live_loop.main()

    assert result == 0
    assert mock_load_state.call_args.kwargs["state_dir"] == "state"
    assert mock_append_decision_log.call_args.kwargs["state_dir"] == "state"


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
         patch("live_loop.save_state") as mock_save_state, \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.write_cycle_export"):
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
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.write_cycle_export"):
        result = live_loop.main()

    assert result == 0
    mock_save_state.assert_called_once()
    saved_state = mock_save_state.call_args[0][0]
    assert saved_state["day"] == datetime.now(ET).date().isoformat()
    assert saved_state["starting_equity"] == 11000.0


def test_main_calls_write_cycle_export_after_save_state():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

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
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.write_cycle_export") as mock_export:
        live_loop.main()

    mock_export.assert_called_once()
    kwargs = mock_export.call_args.kwargs
    assert kwargs["symbols"] == live_loop.WATCHLIST
    assert kwargs["equity"] == 10000.0


def test_process_symbol_cycle_passes_confirmation_bars_to_compute_signals():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

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
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )) as mock_compute, \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.write_cycle_export"):
        live_loop.main()

    assert mock_compute.call_count == len(live_loop.WATCHLIST)
    for call in mock_compute.call_args_list:
        assert "confirmation_bars" in call.kwargs
        # Not just present -- a real per-bar Series, not e.g. None or a
        # scalar fallback, which is exactly how a too-short SIGNAL_LOOKBACK
        # (final-review Fix 1) could silently degrade the filter to K=1
        # (unfiltered) without this test catching it.
        assert isinstance(call.kwargs["confirmation_bars"], pd.Series)


def test_main_passes_loaded_tier_pools_to_process_symbol():
    # Final-review CRITICAL fix: main()'s only real call site must thread
    # tier_pools=tier_pools into process_symbol(), or Task 3's entire
    # tier-scoped sizing/settlement path is unreachable in production no
    # matter what SYMBOL_TIER ends up populated with. process_symbol itself
    # is mocked here (its behavior when tier_pools IS passed is already
    # fully covered by the tier-scoped tests below) -- this test pins only
    # the wiring: that main() forwards the exact object load_tier_pools()
    # returned, as a tier_pools= kwarg, to every WATCHLIST symbol's call.
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}
    fake_tier_pools = {1: 700.0, 2: 200.0, 3: 100.0}

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
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value=fake_tier_pools), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.should_rebalance_this_month", return_value=False), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )), \
         patch("live_loop.process_symbol") as mock_process_symbol, \
         patch("live_loop.write_cycle_export"):
        live_loop.main()

    assert mock_process_symbol.call_count == len(live_loop.WATCHLIST)
    for call in mock_process_symbol.call_args_list:
        assert call.kwargs["tier_pools"] is fake_tier_pools


# --- tier-scoped equity/cash settlement (sub-project 2a/2b)

def test_process_symbol_uses_tier_equity_for_sizing_when_tagged():
    # Tier 2 (not tier 1): tier 1 is spec'd to never reach process_symbol at
    # all (buy-and-hold only, via run_tier1_rebalance) -- using tier 1 here
    # would exercise/normalize exactly the double-routing the spec forbids.
    # See tier_config.py's SYMBOL_TIER/TIER1_SYMBOL_WEIGHTS disjointness
    # assertion (final-review Fix 4).
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True):
        mock_decide, _, _, _, _ = _call(
            symbol="AAPL", signal="buy", equity=10000.0,
            tier_pools={1: 0.0, 2: 500.0, 3: 0.0},
        )
    assert mock_decide.call_args.kwargs["account_equity"] == 500.0


def test_process_symbol_falls_back_to_global_equity_when_untagged():
    # Deliberately untagged (not tier 1 or tier 2) -- this test exercises
    # the "symbol absent from SYMBOL_TIER entirely" fallback path, distinct
    # from the tier-2-tagged tests below.
    with patch.dict("live_loop.SYMBOL_TIER", {}, clear=True):
        mock_decide, _, _, _, _ = _call(
            symbol="AAPL", signal="buy", equity=10000.0,
            tier_pools={1: 0.0, 2: 500.0, 3: 0.0},
        )
    assert mock_decide.call_args.kwargs["account_equity"] == 10000.0


def test_process_symbol_falls_back_to_global_equity_when_tier_pools_not_passed():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True):
        mock_decide, _, _, _, _ = _call(symbol="AAPL", signal="buy", equity=10000.0)
    assert mock_decide.call_args.kwargs["account_equity"] == 10000.0


def test_process_symbol_buy_decrements_tier_pool_cash():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True):
        tier_pools = {1: 0.0, 2: 500.0, 3: 0.0}
        _call(
            symbol="AAPL", signal="buy", current_price=100.0, equity=10000.0,
            tier_pools=tier_pools,
            decide_return=TradeDecision(
                action="buy", reason="all checks passed",
                shares=2.0, stop_price=95.0, target_price=110.0,
            ),
        )
    assert tier_pools[2] == 300.0  # 500.0 - 2.0 * 100.0


def test_process_symbol_stop_exit_increments_tier_pool_cash():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True):
        open_positions = {"AAPL": _position(shares=2.0, stop=98.0, target=103.0)}
        tier_pools = {1: 0.0, 2: 500.0, 3: 0.0}
        _call(
            symbol="AAPL", current_price=97.0, open_positions=open_positions,
            tier_pools=tier_pools,
        )
    assert tier_pools[2] == 694.0  # 500.0 + 2.0 * 97.0


def test_process_symbol_tier_equity_includes_other_same_tier_positions():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2, "BND": 2}, clear=True):
        open_positions = {
            "BND": {"entry_price": 50.0, "shares": 4.0, "stop": 45.0, "target": 60.0, "opened_date": "2024-01-08"},
        }
        mock_decide, _, _, _, _ = _call(
            symbol="AAPL", signal="buy", open_positions=open_positions,
            tier_pools={1: 0.0, 2: 500.0, 3: 0.0},
        )
    assert mock_decide.call_args.kwargs["account_equity"] == 700.0  # 500.0 cash + 50.0*4.0 committed


# --- run_tier1_rebalance (sub-project 2b)

def test_run_tier1_rebalance_returns_empty_when_no_tier1_symbols():
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {}, clear=True):
        orders = run_tier1_rebalance(MagicMock(), MagicMock(), {1: 700.0, 2: 0.0, 3: 0.0})
    assert orders == []


def test_run_tier1_rebalance_submits_orders_and_updates_tier_pool_cash():
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="5")]
    tier_pools = {1: 200.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 1.0}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        orders = run_tier1_rebalance(trading_client, MagicMock(), tier_pools)
    # tier1_equity = 200.0 cash + 5.0 held * 100.0 price = 700.0
    # target_value = 700.0 * 1.0 = 700.0; current_value = 5.0 * 100.0 = 500.0
    # drift = (500.0 - 700.0) / 700.0 =~ -0.286 < -0.05 -> buy (700-500)/100 = 2.0 shares
    assert len(orders) == 1
    assert orders[0].symbol == "VTI"
    assert orders[0].side == "buy"
    assert orders[0].qty == 2.0
    trading_client.submit_order.assert_called_once()
    submitted = trading_client.submit_order.call_args[0][0]
    assert submitted.symbol == "VTI"
    assert submitted.side == OrderSide.BUY
    assert tier_pools[1] == 0.0  # 200.0 - 2.0 * 100.0


def test_run_tier1_rebalance_skips_symbol_with_no_recent_bars():
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = []
    tier_pools = {1: 700.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 1.0}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[]):
        orders = run_tier1_rebalance(trading_client, MagicMock(), tier_pools)
    assert orders == []
    trading_client.submit_order.assert_not_called()
    assert tier_pools[1] == 700.0  # untouched
