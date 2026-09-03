import os
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests
from alpaca.trading.enums import OrderSide

from graywind_strategy import trade_approval
from graywind_strategy.gate_result import GateResult
from graywind_strategy.pipeline import MACRO_UNAVAILABLE_DETAIL, TradeDecision
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.tier1_rebalance import RebalanceOrder
import live_loop
from live_loop import is_market_hours, process_symbol, process_pending_trades, run_tier1_rebalance

ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def isolate_equity_history():
    """main() loads and persists rolling-drawdown equity history through
    state_store. Every main() test below patches the other state_store calls
    but would otherwise leave these two unpatched, writing into the repo's
    REAL state/ directory (and state/small/ in the test that sets
    GRAYWIND_STATE_DIR) as a side effect of running the suite. Autouse so a
    future main() test cannot reintroduce that leak by forgetting to patch.
    Yields the mocks so a test can assert on how they were called.
    """
    with patch("live_loop.load_equity_history", return_value=[]) as load_mock, \
         patch("live_loop.save_equity_history") as save_mock:
        yield load_mock, save_mock


@pytest.fixture(autouse=True)
def isolate_pending_trades():
    """main() also loads and persists pending trade-approval proposals
    through state_store (load_pending_trades/save_pending_trades). Same
    rationale as isolate_equity_history above: every main() test patches the
    other state_store calls but would otherwise leave these two unpatched,
    writing real state/pending_trades.csv (and state/small/pending_trades.csv)
    files into the repo's actual state/ directory as a side effect of running
    the suite. Autouse so a future main() test can't reintroduce that leak by
    forgetting to patch. A separate fixture from isolate_equity_history
    (rather than folded into it) so existing `mock_load, mock_save =
    isolate_equity_history` unpacking at every call site doesn't need to
    change shape. Yields the mocks so a test can assert on how they were
    called.
    """
    with patch("live_loop.load_pending_trades", return_value={}) as load_mock, \
         patch("live_loop.save_pending_trades") as save_mock:
        yield load_mock, save_mock


@pytest.fixture(autouse=True)
def isolate_tier1_holdings():
    """main() also loads and persists last-known tier-1 holdings through
    state_store (load_tier1_holdings/save_tier1_holdings), used to defer a
    tier-1 sell's tier_pools[1] credit until the resulting holdings decrease
    is actually observed. Same rationale and pattern as isolate_pending_trades
    above -- autouse so a future main() test can't reintroduce a real-file-
    write leak by forgetting to patch.
    """
    with patch("live_loop.load_tier1_holdings", return_value={}) as load_mock, \
         patch("live_loop.save_tier1_holdings") as save_mock:
        yield load_mock, save_mock


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
          drawdown_breaker=None, equity=10000.0, tier_pools=None, pending_trades=None):
    open_positions = {} if open_positions is None else open_positions
    trading_client = MagicMock() if trading_client is None else trading_client
    pdt_throttle = MagicMock() if pdt_throttle is None else pdt_throttle
    drawdown_breaker = MagicMock() if drawdown_breaker is None else drawdown_breaker
    pending_trades = {} if pending_trades is None else pending_trades
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
            pending_trades=pending_trades, github_token="tok", repo="me/graywind",
            account_label="100k",
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
    # The reservation-under-cap outcome now shows up as a buy *proposal*
    # (propose_trade called, symbol entered into pending_trades) rather than
    # an executed order, since process_symbol no longer executes buys itself.
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))
    open_positions = {
        "SPY": _position(shares=5, stop=400.0, target=420.0, opened_date="2024-01-08"),
        "MSFT": _position(shares=3, stop=300.0, target=320.0, opened_date="2024-01-07"),  # earlier day
    }
    trading_client = MagicMock()
    pending_trades = {}
    with _passing_gates(), \
         patch("live_loop.trade_approval.propose_trade", return_value=101) as mock_propose:
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=throttle, position_sizer=PositionSizer(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=MagicMock(), pending_trades=pending_trades,
            github_token="tok", repo="me/graywind", account_label="100k",
        )
    mock_propose.assert_called_once()
    trading_client.submit_order.assert_not_called()
    assert "AAPL" not in open_positions
    assert "AAPL" in pending_trades


# --- dashboard export collection: process_symbol optionally records what
# happened this cycle into caller-supplied cycle_trades/symbol_statuses,
# defaulting to None (no-op) so every pre-existing call site above is
# unaffected.

def test_process_symbol_proposes_buy_instead_of_executing():
    # SYMBOL_TIER is patched explicitly here (rather than relying on AAPL's real tag) so this
    # test is isolated from tier_config.py's actual contents -- AAPL is tagged tier 2 for real
    # once the dual-account/tier-symbols plan has shipped, and this test's `tier=2` expectation
    # must track that, not silently drift to `None` if tier_config.py ever changes.
    cycle_trades = []
    symbol_statuses = {}
    pending_trades = {}
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True), patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
    ), patch("live_loop.trade_approval.propose_trade", return_value=101) as mock_propose:
        trading_client = MagicMock()
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=trading_client, drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
            pending_trades=pending_trades, github_token="tok", repo="me/graywind", account_label="100k",
        )
    mock_propose.assert_called_once_with(
        symbol="AAPL", side="buy", qty=10, price=100.0, tier=2, account_label="100k",
        reasoning="signal=buy", github_token="tok", repo="me/graywind", session=requests,
    )
    trading_client.submit_order.assert_not_called()
    assert cycle_trades == []  # not a real trade yet -- just a proposal
    assert symbol_statuses["AAPL"]["action"] == "proposed"
    assert pending_trades["AAPL"] == {
        "issue_number": 101, "side": "buy", "qty": 10, "price_at_proposal": 100.0,
        "stop_price": 98.0, "target_price": 103.0, "tier": 2, "proposed_date": "2024-01-08",
    }


def test_process_symbol_skips_duplicate_proposal_for_already_pending_symbol():
    pending_trades = {
        "AAPL": {
            "issue_number": 99, "side": "buy", "qty": 5.0, "price_at_proposal": 95.0,
            "stop_price": 90.0, "target_price": 100.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.propose_trade") as mock_propose:
        _call(
            symbol="AAPL", signal="buy", pending_trades=pending_trades,
            decide_return=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
        )
    mock_propose.assert_not_called()
    assert pending_trades["AAPL"]["issue_number"] == 99  # untouched, not overwritten


def test_process_symbol_refuses_to_propose_a_buy_for_a_symbol_with_no_tier():
    # Final-review CRITICAL fix: the pre-existing sell path guards its
    # tier_pools debit with `tier is not None`; the buy-proposal path dropped
    # that guard. A WATCHLIST symbol missing from SYMBOL_TIER would be proposed
    # with tier=None, round-trip through pending_trades.csv as None, and then
    # KeyError on `tier_pools[None]` at execution time -- AFTER the order was
    # already submitted, leaving the row in place to be resubmitted every
    # cycle. It would also create a GitHub label literally reading "tier:None".
    # tier_config.py calls SYMBOL_TIER "a living list", so this is armed by the
    # next watchlist change, not hypothetical. Refuse to propose instead.
    cycle_trades = []
    symbol_statuses = {}
    decision_rows = []
    pending_trades = {}
    with patch.dict("live_loop.SYMBOL_TIER", {}, clear=True), patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="signal=buy", shares=10, stop_price=98.0, target_price=103.0),
    ), patch("live_loop.trade_approval.propose_trade") as mock_propose:
        trading_client = MagicMock()
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=trading_client, drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00", cycle_trades=cycle_trades,
            symbol_statuses=symbol_statuses, decision_rows=decision_rows,
            tier_pools={1: 0.0, 2: 500.0, 3: 0.0},
            pending_trades=pending_trades, github_token="tok", repo="me/graywind", account_label="100k",
        )
    mock_propose.assert_not_called()
    trading_client.submit_order.assert_not_called()
    assert pending_trades == {}
    assert cycle_trades == []
    assert symbol_statuses["AAPL"]["position_open"] is False
    # The refusal is scoped to the proposal only -- decide_trade still ran and
    # its decision-log row must still be recorded, or the symbol silently
    # vanishes from decision_log.csv.
    assert len(decision_rows) == 1
    assert decision_rows[0]["symbol"] == "AAPL"


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
    ), patch("live_loop.trade_approval.propose_trade", return_value=101):
        # propose_trade is mocked here purely to keep this decision-log test
        # from making a real network call now that a "buy" decision routes
        # through the proposal path -- the buy/proposal behavior itself is
        # covered by the dedicated tests above, this test only cares about
        # decision_rows, which is populated before the buy/proposal branch.
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


def test_decision_row_distinguishes_macro_unavailable_from_zero_breaches():
    # Same ambiguity I5 fixed for the earnings gate. evaluate_macro_gate returns
    # GateResult(passed=False, detail="MacroDataUnavailable") with value=None when
    # the upstream Bullion feed cannot answer, which collapsed to "" -- identical
    # to the macro gate never having been reached. That made a dead upstream
    # indistinguishable from a short-circuit in decision_log.csv, so nothing could
    # alarm on it.
    decision_rows = []
    decision = TradeDecision(
        action="blocked", reason="macro_gate",
        gate_readings=[
            GateResult(passed=True, value=15.0),
            GateResult(passed=True, value=0.05),
            GateResult(passed=True, value=12),
            GateResult(passed=False, detail=MACRO_UNAVAILABLE_DETAIL),  # value stays None
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
    assert decision_rows[0]["macro_breaches"] == "unavailable"


def test_decision_row_leaves_macro_blank_when_the_gate_was_never_reached():
    decision_rows = []
    decision = TradeDecision(
        action="blocked", reason="vix_gate",
        gate_readings=[GateResult(passed=False, value=40.0)],  # blocked at vix; macro never ran
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
    assert decision_rows[0]["macro_breaches"] == ""


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


def test_process_symbol_records_debate_row_when_llm_client_given():
    open_positions = {}
    fake_result = {
        "vader_score": 0.1, "vader_gate_result": True,
        "debate_score": 0.4, "debate_reasoning": "net bullish",
    }
    debate_rows = []
    with patch("live_loop.evaluate_shadow_debate", return_value=fake_result) as mock_debate:
        live_loop.process_symbol(
            symbol="AAPL", signal="hold", current_price=150.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(can_open_day_trade=lambda *a, **kw: True),
            position_sizer=MagicMock(), drawdown_breaker_ok=True, fred_api_key="k",
            news_client=object(), finnhub_api_key="k", trading_client=MagicMock(),
            drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-27T10:00:00-04:00",
            llm_client=object(), debate_cache={}, debate_rows=debate_rows,
        )

    mock_debate.assert_called_once()
    assert debate_rows == [{
        "timestamp": "2026-08-27T10:00:00-04:00", "symbol": "AAPL", **fake_result,
    }]


def test_process_symbol_debate_exception_does_not_block_real_decision_or_propagate():
    open_positions = {}
    with patch("live_loop.evaluate_shadow_debate", side_effect=RuntimeError("rate limited")), \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")) as mock_decide:
        # Must not raise -- the whole point of fail-open.
        live_loop.process_symbol(
            symbol="AAPL", signal="buy", current_price=150.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(can_open_day_trade=lambda *a, **kw: True),
            position_sizer=MagicMock(), drawdown_breaker_ok=True, fred_api_key="k",
            news_client=object(), finnhub_api_key="k", trading_client=MagicMock(),
            drawdown_breaker=MagicMock(),
            llm_client=object(), debate_cache={}, debate_rows=[],
        )

    mock_decide.assert_called_once()  # the real decision still ran


def test_process_symbol_skips_debate_entirely_when_llm_client_not_given():
    open_positions = {}
    with patch("live_loop.evaluate_shadow_debate") as mock_debate, \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")):
        live_loop.process_symbol(
            symbol="AAPL", signal="hold", current_price=150.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(can_open_day_trade=lambda *a, **kw: True),
            position_sizer=MagicMock(), drawdown_breaker_ok=True, fred_api_key="k",
            news_client=object(), finnhub_api_key="k", trading_client=MagicMock(),
            drawdown_breaker=MagicMock(),
        )

    mock_debate.assert_not_called()


def test_process_symbol_does_not_debate_an_already_held_position():
    open_positions = {"AAPL": {
        "entry_price": 100.0, "shares": 5, "stop": 90.0, "target": 130.0,
        "opened_date": "2024-01-05",
    }}
    with patch("live_loop.evaluate_shadow_debate") as mock_debate:
        live_loop.process_symbol(
            symbol="AAPL", signal="hold", current_price=110.0, today=date(2024, 1, 8),
            open_positions=open_positions, equity=10000.0,
            pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            llm_client=object(), debate_cache={}, debate_rows=[],
        )

    mock_debate.assert_not_called()


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


def _run_main_with_equity(equity, load_equity_history_mock, history, state=None):
    """Drives main() end-to-end with the I/O boundary faked, returning the
    decide_trade mock so a caller can inspect what the wiring actually passed.
    """
    load_equity_history_mock.return_value = history
    fake_account = MagicMock()
    fake_account.equity = str(equity)
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []
    fake_state = state if state is not None else {
        "day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {},
    }

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
         patch("live_loop.fetch_bars", return_value=[
             _FakeBar(100.0, datetime(2024, 1, 8, 10, 0, tzinfo=ET))]), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="buy", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )), \
         patch("live_loop.decide_trade",
               return_value=TradeDecision(action="hold", reason="no buy signal")) as mock_decide, \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.write_cycle_export"):
        assert live_loop.main() == 0
    return mock_decide


def test_main_blocks_entries_when_the_rolling_drawdown_breaker_has_tripped(isolate_equity_history):
    # Without this test the whole rolling-breaker wiring in main() could be
    # deleted and every other test would still pass -- they all run against an
    # empty history, which the breaker treats as permissive cold start.
    mock_load_equity_history, _ = isolate_equity_history
    today = date.today()
    # -10% off a peak two days ago: trips the 7d/5% breaker (and the 30d/10%).
    history = [(today - timedelta(days=2), 10000.0)]
    mock_decide = _run_main_with_equity(9000.0, mock_load_equity_history, history)

    assert mock_decide.called
    assert mock_decide.call_args.kwargs["drawdown_breaker_ok"] is False


def test_main_allows_entries_when_the_rolling_drawdown_is_within_limits(isolate_equity_history):
    mock_load_equity_history, _ = isolate_equity_history
    today = date.today()
    history = [(today - timedelta(days=2), 10000.0)]
    # -1%: well inside both rolling windows, and the daily breaker is untripped.
    mock_decide = _run_main_with_equity(9900.0, mock_load_equity_history, history)

    assert mock_decide.called
    assert mock_decide.call_args.kwargs["drawdown_breaker_ok"] is True


def test_main_persists_todays_equity_into_the_rolling_history(isolate_equity_history):
    mock_load_equity_history, mock_save_equity_history = isolate_equity_history
    today = date.today()
    history = [(today - timedelta(days=2), 10000.0)]
    _run_main_with_equity(9900.0, mock_load_equity_history, history)

    saved_rows = mock_save_equity_history.call_args[0][0]
    assert (today, 9900.0) in saved_rows
    # the loaded row is carried forward, not dropped
    assert (today - timedelta(days=2), 10000.0) in saved_rows


def test_main_survives_an_intraday_wipeout_without_abandoning_the_cycle(isolate_equity_history):
    # record_equity rejects non-positive equity, and it sits above the WATCHLIST
    # loop with no `except` between, so an unguarded raise would skip the
    # stop/target exit checks in exactly the scenario where exits matter most.
    # The daily breaker's own start_new_day guard does NOT cover this case: with
    # a valid start-of-day baseline already persisted it succeeds, and only the
    # current equity has collapsed.
    mock_load_equity_history, _ = isolate_equity_history
    mid_day_wipeout_state = {
        "day_trade_dates": [],
        "day": date.today().isoformat(),
        "starting_equity": 10000.0,
        "open_positions": {},
    }
    mock_decide = _run_main_with_equity(
        0.0, mock_load_equity_history, [], state=mid_day_wipeout_state,
    )
    assert mock_decide.called  # the cycle body still ran


def test_main_threads_graywind_state_dir_env_var_into_every_state_call(isolate_equity_history):
    mock_load_equity_history, mock_save_equity_history = isolate_equity_history
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
    # The rolling-drawdown history is per-account too: sharing one file between
    # the main and small accounts would blend two different equity curves into
    # one drawdown calculation and trip (or fail to trip) both breakers wrongly.
    assert mock_load_equity_history.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_equity_history.call_args.kwargs["state_dir"] == "state/small"


def test_main_defaults_graywind_state_dir_to_state_when_env_var_unset(isolate_equity_history):
    mock_load_equity_history, _ = isolate_equity_history
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
    assert mock_load_equity_history.call_args.kwargs["state_dir"] == "state"


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


def test_main_constructs_llm_client_when_deepseek_key_set():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
             "DEEPSEEK_API_KEY": "fake-deepseek-key",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.openai.OpenAI") as mock_openai_ctor, \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.log_news_debate") as mock_log_news_debate, \
         patch("live_loop.write_cycle_export"):
        result = live_loop.main()

    assert result == 0
    mock_openai_ctor.assert_called_once_with(
        api_key="fake-deepseek-key", base_url="https://api.deepseek.com",
        timeout=20.0, max_retries=1,
    )
    mock_log_news_debate.assert_called_once()
    assert mock_log_news_debate.call_args.args[0] == []  # no symbols processed (fetch_bars -> [])


def test_main_skips_llm_client_construction_when_deepseek_key_unset():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
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
         patch("live_loop.openai.OpenAI") as mock_openai_ctor, \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.log_news_debate") as mock_log_news_debate, \
         patch("live_loop.write_cycle_export"):
        os.environ.pop("DEEPSEEK_API_KEY", None)
        result = live_loop.main()

    assert result == 0
    mock_openai_ctor.assert_not_called()
    mock_log_news_debate.assert_called_once()
    assert mock_log_news_debate.call_args.args[0] == []


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


def _main_with_patches(extra_patches=None, tier_pools=None, rebalance_state=None,
                        should_rebalance=False):
    """Runs main() with the standard main()-test patch set (copied from
    test_main_passes_loaded_tier_pools_to_process_symbol, which is the
    canonical one) so no test below reaches the network or writes into the
    repo's real state/ or dashboard_export/ directories. `extra_patches` is a
    list of already-constructed patchers the caller wants active and inspects
    afterwards.
    """
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []
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
         patch("live_loop.load_tier_pools", return_value=tier_pools or {1: 700.0, 2: 200.0, 3: 100.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state",
               return_value=rebalance_state if rebalance_state is not None else {"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.should_rebalance_this_month", return_value=should_rebalance), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
             signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
         )), \
         patch("live_loop.process_symbol"), \
         patch("live_loop.append_decision_log"), \
         patch("live_loop.log_news_debate"), \
         patch("live_loop.write_cycle_export"):
        started = [p.start() for p in (extra_patches or [])]
        try:
            result = live_loop.main()
        finally:
            for p in (extra_patches or []):
                p.stop()
    return result, started


def test_main_passes_rolling_breakers_into_process_pending_trades():
    # main()'s real call site for process_pending_trades is otherwise untested
    # -- every other test calls that function directly with hand-built
    # arguments. This branch already shipped one signature-mismatch bug on this
    # exact function, and a missing rolling_breakers kwarg would silently let an
    # approved proposal execute against only the DAILY breaker while main()'s
    # own proposal gate requires the rolling ones too.
    patcher = patch("live_loop.process_pending_trades")
    result, (mock_process_pending,) = _main_with_patches(extra_patches=[patcher])

    assert result == 0
    mock_process_pending.assert_called_once()
    assert "rolling_breakers" in mock_process_pending.call_args.kwargs
    breakers = mock_process_pending.call_args.kwargs["rolling_breakers"]
    assert breakers  # the real list main() built, not None/empty
    assert all(hasattr(b, "can_open_new_trade") for b in breakers)


def test_main_does_not_stamp_rebalance_month_when_a_buy_was_only_proposed():
    # A tier-1 rebalance buy is now only PROPOSED, not executed. Stamping
    # last_rebalance_month regardless means an unapproved proposal that expires
    # at end of day silently skips the drift correction for a whole month,
    # because should_rebalance_this_month won't fire again until the next one.
    rebalance_state = {"last_rebalance_month": None}

    def fake_rebalance(*args, **kwargs):
        kwargs["pending_trades"]["SPY"] = {
            "issue_number": 42, "side": "buy", "qty": 2.0, "price_at_proposal": 100.0,
            "stop_price": None, "target_price": None, "tier": 1,
            "proposed_date": kwargs["today"].isoformat(),
        }
        return [RebalanceOrder(symbol="SPY", side="buy", qty=2.0)]

    patcher = patch("live_loop.run_tier1_rebalance", side_effect=fake_rebalance)
    result, (mock_rebalance,) = _main_with_patches(
        extra_patches=[patcher], rebalance_state=rebalance_state, should_rebalance=True,
    )

    assert result == 0
    mock_rebalance.assert_called_once()
    assert rebalance_state["last_rebalance_month"] is None  # retried next cycle, not skipped


def test_main_stamps_rebalance_month_when_no_buy_is_left_pending():
    # The complement: a rebalance that produced nothing to approve (no orders,
    # or sells only -- sells still execute immediately) is genuinely done for
    # the month and must stamp, or it would re-run every single cycle forever.
    rebalance_state = {"last_rebalance_month": None}
    patcher = patch("live_loop.run_tier1_rebalance",
                    return_value=[RebalanceOrder(symbol="SPY", side="sell", qty=2.0)])
    result, _ = _main_with_patches(
        extra_patches=[patcher], rebalance_state=rebalance_state, should_rebalance=True,
    )

    assert result == 0
    assert rebalance_state["last_rebalance_month"] == datetime.now(ET).strftime("%Y-%m")


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


def test_process_symbol_buy_proposal_does_not_touch_tier_pool_cash():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 2}, clear=True), \
         patch("live_loop.trade_approval.propose_trade", return_value=101):
        tier_pools = {1: 0.0, 2: 500.0, 3: 0.0}
        _call(
            symbol="AAPL", signal="buy", current_price=100.0, equity=10000.0,
            tier_pools=tier_pools,
            decide_return=TradeDecision(
                action="buy", reason="all checks passed",
                shares=2.0, stop_price=95.0, target_price=110.0,
            ),
        )
    assert tier_pools[2] == 500.0  # unchanged -- only execution (Task 5) touches this


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


def test_run_tier1_rebalance_proposes_buy_instead_of_executing():
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="5")]
    tier_pools = {1: 200.0, 2: 0.0, 3: 0.0}
    pending_trades = {}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 1.0}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]), \
         patch("live_loop.trade_approval.propose_trade", return_value=201) as mock_propose:
        orders = run_tier1_rebalance(
            trading_client, MagicMock(), tier_pools, pending_trades=pending_trades,
            github_token="tok", repo="me/graywind", account_label="100k", today=date(2026, 8, 26),
        )
    # Same underlying drift math as before this task -- see the original test's comment:
    # tier1_equity=700.0, target=700.0, current=500.0, drift=-0.286 -> buy 2.0 shares.
    assert len(orders) == 1
    assert orders[0].symbol == "VTI"
    assert orders[0].side == "buy"
    assert orders[0].qty == 2.0
    trading_client.submit_order.assert_not_called()
    mock_propose.assert_called_once_with(
        symbol="VTI", side="buy", qty=2.0, price=100.0, tier=1, account_label="100k",
        reasoning="tier-1 monthly drift rebalance", github_token="tok", repo="me/graywind",
        session=requests,
    )
    assert tier_pools[1] == 200.0  # unchanged -- only execution (Task 5) touches this
    assert pending_trades["VTI"] == {
        "issue_number": 201, "side": "buy", "qty": 2.0, "price_at_proposal": 100.0,
        "stop_price": None, "target_price": None, "tier": 1, "proposed_date": "2026-08-26",
    }


def test_run_tier1_rebalance_sell_submits_but_defers_pool_credit_until_settlement_observed():
    # Sells still submit immediately (risk-reducing, stays automatic) -- but
    # tier_pools[1] is no longer credited optimistically at submission time.
    # Crediting now happens only once a real holdings decrease is observed
    # on a later cycle (see the credit-on-settlement tests below) -- this
    # closes both the equity-double-count race and the worse case where a
    # DAY order never fills and gets broker-cancelled, since nothing is
    # ever credited for an order that never actually settles.
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="7")]
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]), \
         patch("live_loop.trade_approval.propose_trade") as mock_propose:
        # tier1_equity = 0.0 + 7*100 = 700.0; target = 700*0.6 = 420.0; current = 700.0;
        # drift = (700-420)/700 = 0.4 > 0.05 -> sell (700-420)/100 = 2.8 shares.
        orders = run_tier1_rebalance(trading_client, MagicMock(), tier_pools)
    assert orders[0].side == "sell"
    trading_client.submit_order.assert_called_once()
    mock_propose.assert_not_called()
    assert tier_pools[1] == 0.0  # NOT credited yet -- settlement hasn't been observed


def test_run_tier1_rebalance_credits_pool_when_holdings_decreased_since_last_known():
    # Simulates the cycle AFTER a sell actually settled: get_all_positions()
    # now shows the lower share count, and last_known_holdings still has the
    # pre-sale figure from the prior cycle -- the observed decrease is what
    # triggers the (deferred) credit, priced at this cycle's current price.
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="4.2")]
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    last_known_holdings = {"VTI": 7.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]), \
         patch("live_loop.trade_approval.propose_trade") as mock_propose:
        run_tier1_rebalance(
            trading_client, MagicMock(), tier_pools, last_known_holdings=last_known_holdings,
        )
    assert tier_pools[1] == 280.0  # 0.0 + (7.0 - 4.2) * 100.0
    assert last_known_holdings["VTI"] == 4.2  # updated for the next cycle's comparison


def test_run_tier1_rebalance_no_credit_when_holdings_unchanged():
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="7")]
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    last_known_holdings = {"VTI": 7.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        run_tier1_rebalance(
            trading_client, MagicMock(), tier_pools, last_known_holdings=last_known_holdings,
        )
    assert tier_pools[1] == 0.0  # no observed decrease -- nothing credited


def test_run_tier1_rebalance_defers_credit_when_price_unavailable_and_retries_later():
    # A decrease observed on a cycle where this symbol's bars are
    # unavailable must not be silently lost -- last_known_holdings should
    # NOT advance past it, so a later cycle (once bars return) still
    # detects and credits the same decrease.
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="4.2")]
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    last_known_holdings = {"VTI": 7.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[]):  # no bars this cycle
        run_tier1_rebalance(
            trading_client, MagicMock(), tier_pools, last_known_holdings=last_known_holdings,
        )
    assert tier_pools[1] == 0.0  # can't price the credit yet -- deferred, not lost
    assert last_known_holdings["VTI"] == 7.0  # unchanged, so it's retried next time

    # Next cycle: bars are available again -- the deferred decrease is
    # still detected (baseline never advanced) and credited now.
    fake_bar = MagicMock(close=100.0)
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]), \
         patch("live_loop.trade_approval.propose_trade") as mock_propose:
        run_tier1_rebalance(
            trading_client, MagicMock(), tier_pools, last_known_holdings=last_known_holdings,
        )
    assert tier_pools[1] == 280.0  # 0.0 + (7.0 - 4.2) * 100.0
    assert last_known_holdings["VTI"] == 4.2


def test_run_tier1_rebalance_no_phantom_credit_on_cold_start():
    # No prior last_known_holdings persisted yet (first ever run) --
    # must not be misread as "everything just got sold".
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="7")]
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 0.6}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        run_tier1_rebalance(trading_client, MagicMock(), tier_pools, last_known_holdings={})
    assert tier_pools[1] == 0.0


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


def test_process_pending_trades_expires_stale_proposal():
    pending_trades = {
        "AAPL": {
            "issue_number": 1, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-07",
        },
    }
    with patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.trade_approval.get_owner_reaction") as mock_reaction:
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    mock_close.assert_called_once()
    assert mock_close.call_args.args[0] == 1
    mock_reaction.assert_not_called()  # expired before a reaction was even checked
    assert pending_trades == {}


def test_process_pending_trades_closes_on_owner_rejection():
    pending_trades = {
        "AAPL": {
            "issue_number": 2, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="rejected"), \
         patch("live_loop.trade_approval.close_issue") as mock_close:
        trading_client = MagicMock()
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert pending_trades == {}


def test_process_pending_trades_leaves_undecided_proposal_open():
    pending_trades = {
        "AAPL": {
            "issue_number": 3, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction", return_value=None), \
         patch("live_loop.trade_approval.close_issue") as mock_close:
        trading_client = MagicMock()
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_not_called()
    assert "AAPL" in pending_trades  # still waiting


def test_process_pending_trades_executes_approved_tier2_buy_and_opens_position():
    fake_bar = MagicMock(close=101.0)  # within 2% of the 100.0 proposal price
    pending_trades = {
        "AAPL": {
            "issue_number": 4, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    open_positions = {}
    tier_pools = {1: 0.0, 2: 500.0, 3: 0.0}
    cycle_trades = []
    symbol_statuses = {}
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools=tier_pools, open_positions=open_positions,
            data_client=MagicMock(), cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
        )
    trading_client.submit_order.assert_called_once()
    assert tier_pools[2] == 500.0 - 5.0 * 101.0
    assert open_positions["AAPL"] == {
        "entry_price": 101.0, "shares": 5.0, "stop": 95.0, "target": 110.0,
        "opened_date": "2024-01-08",
    }
    assert cycle_trades[0]["symbol"] == "AAPL"
    assert cycle_trades[0]["side"] == "buy"
    mock_close.assert_called_once()
    assert pending_trades == {}


def test_process_pending_trades_executes_approved_tier1_buy_without_opening_position():
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "SPY": {
            "issue_number": 5, "side": "buy", "qty": 1.0, "price_at_proposal": 100.0,
            "stop_price": None, "target_price": None, "tier": 1, "proposed_date": "2024-01-08",
        },
    }
    open_positions = {}
    tier_pools = {1: 500.0, 2: 0.0, 3: 0.0}
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue"), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools=tier_pools, open_positions=open_positions,
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_called_once()
    assert tier_pools[1] == 400.0  # 500.0 - 1.0 * 100.0
    assert open_positions == {}  # tier-1 holdings are tracked via Alpaca, not open_positions


def test_process_pending_trades_submits_order_and_clears_row_even_if_close_issue_fails():
    # Regression test for a duplicate-buy bug found in review: order
    # submission and pending_trades cleanup on the approved-and-executed
    # path must happen BEFORE the closing close_issue call, not after --
    # otherwise a transient GitHub failure there leaves the row in
    # pending_trades even though the order already went through, and the
    # next cycle re-validates clean and resubmits the SAME order. This is
    # especially dangerous for tier-1 buys, which (per the test above) are
    # never added to open_positions, so there's no already-open-position
    # guard to catch the duplicate.
    fake_bar = MagicMock(close=101.0)  # within 2% of the 100.0 proposal price
    pending_trades = {
        "AAPL": {
            "issue_number": 12, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue",
               side_effect=RuntimeError("transient GitHub error")), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        # close_issue raises, but process_pending_trades must not propagate
        # it -- the order/state cleanup already happened by the time
        # close_issue is even called.
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_called_once()
    assert pending_trades == {}  # cleared regardless of the closing comment's outcome


def test_process_pending_trades_rejects_approved_buy_on_stale_price():
    fake_bar = MagicMock(close=110.0)  # 10% above the 100.0 proposal price -- exceeds 2% tolerance
    pending_trades = {
        "AAPL": {
            "issue_number": 6, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "price moved" in mock_close.call_args.args[1]
    assert pending_trades == {}


def test_process_pending_trades_rejects_approved_buy_when_drawdown_breaker_blocks():
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "AAPL": {
            "issue_number": 7, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = False
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "drawdown" in mock_close.call_args.args[1]


def test_process_pending_trades_rejects_approved_buy_when_rolling_breaker_blocks():
    # main()'s own proposal-creation gate for tier-2/3 buys requires the
    # daily breaker AND every rolling (weekly/monthly) breaker to allow a
    # new trade -- re-validation at approval time must apply the same
    # combined gate, not just the daily breaker, since time has passed
    # since the proposal was made.
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "AAPL": {
            "issue_number": 14, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    blocking_rolling_breaker = MagicMock()
    blocking_rolling_breaker.can_open_new_trade.return_value = False
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(), rolling_breakers=[blocking_rolling_breaker],
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "rolling" in mock_close.call_args.args[1]
    assert pending_trades == {}


def test_process_pending_trades_rejects_approved_buy_when_position_already_open():
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "AAPL": {
            "issue_number": 8, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    open_positions = {"AAPL": _position()}
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions=open_positions,
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "already opened" in mock_close.call_args.args[1]


def test_process_pending_trades_removes_row_on_issue_not_found():
    pending_trades = {
        "AAPL": {
            "issue_number": 9, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction", side_effect=trade_approval.IssueNotFound("gone")):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    assert pending_trades == {}


def test_process_pending_trades_one_symbols_api_failure_does_not_block_others():
    pending_trades = {
        "AAPL": {
            "issue_number": 10, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
        "SERV": {
            "issue_number": 11, "side": "buy", "qty": 20.0, "price_at_proposal": 40.0,
            "stop_price": 38.0, "target_price": 44.0, "tier": 3, "proposed_date": "2024-01-08",
        },
    }

    def fake_get_owner_reaction(issue_number, *args, **kwargs):
        if issue_number == 10:
            raise RuntimeError("transient GitHub API error")
        return "rejected"

    with patch("live_loop.trade_approval.get_owner_reaction", side_effect=fake_get_owner_reaction), \
         patch("live_loop.trade_approval.close_issue") as mock_close:
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    assert "AAPL" in pending_trades  # its own error left it untouched, retried next cycle
    assert "SERV" not in pending_trades  # rejected and closed despite AAPL's error
    mock_close.assert_called_once()


def test_process_pending_trades_refuses_approved_buy_whose_tier_has_no_pool():
    # Companion to process_symbol's tier=None refusal: a row persisted by an
    # earlier build (or a hand-edited pending_trades.csv) can still carry a tier
    # that isn't a tier_pools key. Debiting it raises KeyError *after* the order
    # is submitted, so it must be caught in the re-validation chain and refused
    # before any order goes out -- never submitted-then-crashed.
    fake_bar = MagicMock(close=100.0)
    pending_trades = {
        "AAPL": {
            "issue_number": 13, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": None, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue") as mock_close, \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 500.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    trading_client.submit_order.assert_not_called()
    mock_close.assert_called_once()
    assert "tier" in mock_close.call_args.args[1]
    assert pending_trades == {}


class _PoolsThatFailOnWrite(dict):
    """tier_pools whose debit raises -- stands in for any post-submit_order
    bookkeeping failure inside the approved-and-executing path."""

    def __setitem__(self, key, value):
        raise RuntimeError("tier pool write failed")


def test_process_pending_trades_clears_row_when_bookkeeping_after_the_order_fails():
    # Final-review CRITICAL fix (part 2): once submit_order() has succeeded the
    # trade is irreversibly real, so the pending_trades row must be dropped
    # immediately -- before the tier_pools debit, the open_positions update and
    # close_issue. Otherwise ANY exception in that tail is swallowed by the
    # outer per-symbol except, the row survives, and the next cycle re-validates
    # clean and submits the SAME order again, every cycle, until the price
    # drifts past tolerance or the day ends.
    fake_bar = MagicMock(close=101.0)  # within 2% of the 100.0 proposal price
    pending_trades = {
        "AAPL": {
            "issue_number": 14, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    trading_client = MagicMock()
    drawdown_breaker = MagicMock()
    drawdown_breaker.can_open_new_trade.return_value = True
    with patch("live_loop.trade_approval.get_owner_reaction", return_value="approved"), \
         patch("live_loop.trade_approval.close_issue"), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools=_PoolsThatFailOnWrite({1: 0.0, 2: 500.0, 3: 0.0}),
            open_positions={}, data_client=MagicMock(),
        )
    trading_client.submit_order.assert_called_once()
    assert pending_trades == {}  # never left behind to be resubmitted next cycle


def test_process_pending_trades_force_removes_stale_row_when_close_issue_keeps_failing():
    # A stuck row is a permanent, silent, per-symbol outage: duplicate-proposal
    # suppression in process_symbol/run_tier1_rebalance is keyed on
    # `symbol in pending_trades`, so a row that can never be deleted means that
    # symbol can never be proposed again. Expiring a proposal is local
    # bookkeeping -- it must not be gated on GitHub accepting the closing
    # comment.
    pending_trades = {
        "AAPL": {
            "issue_number": 15, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-05",
        },
    }
    with patch("live_loop.trade_approval.close_issue",
               side_effect=RuntimeError("issue deleted out-of-band (404)")) as mock_close, \
         patch("live_loop.trade_approval.get_owner_reaction") as mock_reaction:
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    mock_close.assert_called_once()
    mock_reaction.assert_not_called()
    assert pending_trades == {}  # removed despite close_issue never succeeding


def test_process_pending_trades_force_removes_a_row_that_cannot_even_be_date_checked():
    # Backstop for the same property one level out: whatever raises while
    # resolving a symbol, a row that is not from today must never survive the
    # cycle. Here the row is malformed (no proposed_date at all, e.g. a
    # hand-edited pending_trades.csv), so it raises before any branch can
    # handle it -- without the purge in the outer except it would be stuck
    # forever and disable AAPL permanently.
    pending_trades = {
        "AAPL": {
            "issue_number": 16, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2,
        },
    }
    with patch("live_loop.trade_approval.close_issue"), \
         patch("live_loop.trade_approval.get_owner_reaction"):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    assert pending_trades == {}


def test_process_pending_trades_keeps_todays_row_after_a_transient_error():
    # The flip side of the purge above: a row proposed TODAY that hit a
    # transient error must still be retried next cycle, not thrown away.
    pending_trades = {
        "AAPL": {
            "issue_number": 17, "side": "buy", "qty": 5.0, "price_at_proposal": 100.0,
            "stop_price": 95.0, "target_price": 110.0, "tier": 2, "proposed_date": "2024-01-08",
        },
    }
    with patch("live_loop.trade_approval.get_owner_reaction",
               side_effect=RuntimeError("transient GitHub API error")):
        process_pending_trades(
            pending_trades, today=date(2024, 1, 8), trading_client=MagicMock(),
            drawdown_breaker=MagicMock(), github_token="tok", repo="me/graywind",
            owner_username="me", tier_pools={1: 0.0, 2: 0.0, 3: 0.0}, open_positions={},
            data_client=MagicMock(),
        )
    assert "AAPL" in pending_trades
