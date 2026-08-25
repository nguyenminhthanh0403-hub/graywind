from unittest.mock import patch

import pandas as pd
import pytest

from graywind_strategy.backtester import max_drawdown, run_backtest, sharpe_ratio, win_rate
from graywind_strategy.pipeline import TradeDecision
from graywind_strategy.strategy_engine import compute_signals

# Computed independently via sharpe_ratio([10000.0, 10000.0, 10000.0, 10120.0,
# 10120.0], periods_per_year=PERIODS_PER_YEAR_15MIN) -- see
# test_run_backtest_sharpe_pins_the_15min_periods_per_year_scaling.
EXPECTED_SHARPE_FOR_PINNED_CURVE = 46.73328578219169


def test_sharpe_ratio_of_flat_equity_curve_is_zero():
    # Zero variance in returns -> Sharpe is defined as 0.0, not a division error.
    assert sharpe_ratio([10000, 10000, 10000, 10000], periods_per_year=252) == 0.0


def test_sharpe_ratio_positive_for_a_steadily_rising_equity_curve():
    curve = [10000 * (1.001 ** i) for i in range(50)]
    assert sharpe_ratio(curve, periods_per_year=252) > 0.0


def test_max_drawdown_of_monotonically_rising_curve_is_zero():
    assert max_drawdown([100, 110, 120, 130]) == 0.0


def test_max_drawdown_measures_the_worst_peak_to_trough_drop():
    # Peak 150, trough 120 -> (150-120)/150 = 0.2
    assert max_drawdown([100, 150, 130, 120, 140]) == 0.2


def test_win_rate_of_no_trades_is_zero():
    assert win_rate([]) == 0.0


def test_win_rate_counts_profitable_round_trips():
    trades = [
        {"symbol": "AAPL", "action": "buy", "price": 100.0, "shares": 10},
        {"symbol": "AAPL", "action": "sell", "price": 105.0, "shares": 10},  # +$50, win
        {"symbol": "SPY", "action": "buy", "price": 400.0, "shares": 5},
        {"symbol": "SPY", "action": "sell", "price": 395.0, "shares": 5},   # -$25, loss
    ]
    assert win_rate(trades) == 0.5


def test_run_backtest_sharpe_pins_the_15min_periods_per_year_scaling():
    # Regression test for the Sharpe-scale fix: run_backtest's BacktestResult
    # construction explicitly passes periods_per_year=PERIODS_PER_YEAR_15MIN
    # (26 bars/session * 252 = 6552) into sharpe_ratio, instead of letting it
    # fall back to sharpe_ratio's own default of 252 (which assumes one bar
    # per trading day and would understate Sharpe by ~sqrt(26) for this
    # project's 15-minute bars). No other existing test pins an exact sharpe
    # value, so reverting that one keyword argument to the default would
    # silently pass every other test in this file.
    #
    # decide_trade is mocked (same technique as the pending-same-day-trades
    # test below) to force one fully deterministic buy-then-target-exit
    # round trip. Orders fill at the *next* bar's open (see
    # test_run_backtest_fills_entry_at_the_next_bars_open, not this bar's
    # close): the buy decided on t1's close fills at t2's open (100.0); the
    # target hit detected on t3's close (110.0 >= target 110.0) fills at
    # t4's open (112.0). That produces equity_curve
    # [10000, 10000, 10000, 10120, 10120] -- the expected sharpe below was
    # computed independently from that exact curve via
    # sharpe_ratio(equity_curve, periods_per_year=6552).
    times = pd.to_datetime([
        "2024-01-08 09:30:00", "2024-01-08 09:45:00",
        "2024-01-08 10:00:00", "2024-01-08 10:15:00", "2024-01-08 10:30:00",
    ])
    df_by_symbol = {
        "AAPL": pd.DataFrame({
            "time": times,
            "open": [99.0, 100.0, 107.0, 112.0, 108.0],
            "close": [100.0, 105.0, 110.0, 108.0, 999.0],
        }),
    }

    call_count = 0

    def fake_decide_trade(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return TradeDecision(
                action="buy", reason="test", shares=10, stop_price=90.0, target_price=110.0
            )
        return TradeDecision(action="hold", reason="no buy signal")

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=10000.0)

    assert result.equity_curve == [10000.0, 10000.0, 10000.0, 10120.0, 10120.0]
    assert result.sharpe == pytest.approx(EXPECTED_SHARPE_FOR_PINNED_CURVE, rel=1e-9)


def test_run_backtest_fills_entry_at_the_next_bars_open_not_the_signal_bars_close():
    # Regression test for the lookahead-bias fix: a signal computed from a
    # bar's close is only knowable once that bar finishes printing, so a
    # live system reacting to it could not have been filled at that exact
    # same close. The resulting buy must fill at the *next* bar's open
    # (105.0) instead -- not t1's close (100.0) that produced the signal,
    # and not t1's own open (99.0).
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    t2 = pd.Timestamp("2024-01-08 09:45:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({
            "time": [t1, t2], "open": [99.0, 105.0], "close": [100.0, 999.0],
        }),
    }

    def fake_decide_trade(**kwargs):
        return TradeDecision(
            action="buy", reason="test", shares=1, stop_price=1.0, target_price=99999.0
        )

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=10000.0)

    assert result.trades == [
        {"symbol": "AAPL", "action": "buy", "price": 105.0, "shares": 1, "time": t2},
    ]


def test_run_backtest_fills_exit_at_the_next_bars_open_not_the_trigger_bars_close():
    # Same lookahead-bias fix, for exits: a stop/target crossing detected on
    # a bar's close must fill at the *next* bar's open, not the triggering
    # close itself. AAPL enters at t2's open (102.0, deferred from t1's buy
    # signal). t2's close (80.0) crosses the stop (90.0), so the exit fills
    # at t3's open (95.0) -- not 80.0, the close that triggered it.
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    t2 = pd.Timestamp("2024-01-08 09:45:00")
    t3 = pd.Timestamp("2024-01-08 10:00:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({
            "time": [t1, t2, t3],
            "open": [99.0, 102.0, 95.0],
            "close": [100.0, 80.0, 999.0],
        }),
    }

    call_count = 0

    def fake_decide_trade(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return TradeDecision(
                action="buy", reason="test", shares=10, stop_price=90.0, target_price=9999.0
            )
        return TradeDecision(action="hold", reason="test")

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=10000.0)

    sell_trades = [t for t in result.trades if t["action"] == "sell"]
    assert sell_trades == [
        {"symbol": "AAPL", "action": "sell", "price": 95.0, "shares": 10, "time": t3},
    ]


def test_run_backtest_forwards_pending_same_day_trades_when_symbols_race_to_open():
    # Regression test for the PDT same-day-reservation fix (see
    # task-11-report.md): when two symbols share the same bar timestamp and
    # neither has an open position yet, opening the first (AAPL) must be
    # reflected as a *pending* same-day trade when deciding whether to open
    # the second (SPY) moments later -- otherwise both could independently
    # pass a realized-only PDT check and later close same-day, producing a
    # real PDT violation (exactly what the original integration run found).
    #
    # decide_trade is mocked here specifically so this test doesn't depend
    # on reverse-engineering real RSI/MA signal generation -- it directly
    # inspects the `pending_same_day_trades` kwarg run_backtest computes and
    # forwards on each call. If the `pending_today` computation or its
    # forwarding into decide_trade were removed, SPY's call would receive
    # pending_same_day_trades=0 (decide_trade's default) instead of 1, and
    # the second assertion below would fail.
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": [t1], "open": [100.0], "close": [100.0]}),
        "SPY": pd.DataFrame({"time": [t1], "open": [50.0], "close": [50.0]}),
    }

    calls = []

    def fake_decide_trade(**kwargs):
        calls.append(kwargs)
        return TradeDecision(
            action="buy", reason="test", shares=1, stop_price=1.0, target_price=9999.0
        )

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=10000.0)

    assert [c["symbol"] for c in calls] == ["AAPL", "SPY"]
    assert calls[0]["pending_same_day_trades"] == 0  # nothing open yet when AAPL is evaluated
    assert calls[1]["pending_same_day_trades"] == 1  # AAPL's just-opened position is pending

    # Both symbols share one timestamp -> the equity curve (fixed in the
    # same change) must have exactly one point, not one per (bar, symbol)
    # row, or max_drawdown/sharpe_ratio would be corrupted by duplicate
    # points at every real moment in time.
    assert len(result.equity_curve) == 1


def test_run_backtest_trips_drawdown_breaker_on_unrealized_loss_alone():
    # Regression test: DrawdownBreaker's own docstring says it halts trading
    # once "realized+unrealized losses" reach the daily threshold, but
    # run_backtest was feeding it the realized-only `equity` variable, which
    # never moves while a losing position stays open (it only moves when a
    # position is *closed*). An open position that drifts deep into
    # unrealized loss without ever hitting its own stop must still be able
    # to trip the shared daily breaker and block a *different* symbol from
    # opening a new position that same day.
    #
    # AAPL's buy is decided at t1 (mocked) and fills at t2's open (100.0,
    # 10 shares, stop=1.0/target=9999.0 so nothing about AAPL's own
    # stop/target triggers within this test). At t2, AAPL's close drops to
    # 80: unrealized loss = (100-80)*10 = $200 = 2% of the $10,000 starting
    # equity, i.e. exactly at run_backtest's default
    # max_daily_loss_fraction=0.02 threshold, so the breaker should trip.
    # SPY, evaluated moments later at the same t2 bar, must then see
    # drawdown_breaker_ok=False on its decide_trade call.
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    t2 = pd.Timestamp("2024-01-08 09:45:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": [t1, t2], "open": [100.0, 100.0], "close": [100.0, 80.0]}),
        "SPY": pd.DataFrame({"time": [t1, t2], "open": [50.0, 50.0], "close": [50.0, 50.0]}),
    }

    calls = []

    def fake_decide_trade(**kwargs):
        calls.append(kwargs)
        if kwargs["symbol"] == "AAPL" and kwargs["as_of_date"] == t1.date():
            return TradeDecision(
                action="buy", reason="test", shares=10, stop_price=1.0, target_price=9999.0
            )
        return TradeDecision(action="hold", reason="test")

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        run_backtest(df_by_symbol, starting_equity=10000.0)

    spy_calls = [c for c in calls if c["symbol"] == "SPY"]
    assert len(spy_calls) == 2
    assert spy_calls[0]["drawdown_breaker_ok"] is True  # t1: no loss yet
    assert spy_calls[1]["drawdown_breaker_ok"] is False  # t2: AAPL's unrealized loss tripped it


def test_run_backtest_clamps_a_buy_to_cash_left_after_earlier_same_bar_fills():
    # Regression test: decide_trade sizes each symbol's position off the full
    # running `equity`, with no awareness of capital already committed to
    # other symbols opened earlier the same bar. A real broker would reject
    # (or partial-fill) an order that outspends available buying power; the
    # backtester must simulate that instead of letting combined notional
    # across symbols exceed account equity.
    #
    # starting_equity=1000. Both symbols' buys are decided at t1 and fill at
    # t2's open. AAPL (processed first -- dict insertion order) fills for 6
    # shares @ $100 = $600 notional, leaving $400 cash. SPY, filling moments
    # later at the same t2 bar, is also sized (by the mocked decide_trade)
    # for 6 shares @ $100 = $600 notional -- but only $400 is actually
    # left, so it must be clamped down to what $400 can actually buy:
    # floor(400 / 100) = 4 shares.
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    t2 = pd.Timestamp("2024-01-08 09:45:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": [t1, t2], "open": [99.0, 100.0], "close": [100.0, 100.0]}),
        "SPY": pd.DataFrame({"time": [t1, t2], "open": [99.0, 100.0], "close": [100.0, 100.0]}),
    }

    def fake_decide_trade(**kwargs):
        return TradeDecision(
            action="buy", reason="test", shares=6, stop_price=1.0, target_price=9999.0
        )

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=1000.0)

    buys_by_symbol = {t["symbol"]: t for t in result.trades if t["action"] == "buy"}
    assert buys_by_symbol["AAPL"]["shares"] == 6  # first mover gets what it asked for
    assert buys_by_symbol["SPY"]["shares"] == 4  # clamped to the $400 actually left


def test_run_backtest_skips_a_buy_when_no_cash_is_left_after_earlier_same_bar_fills():
    # Same capital-check fix as above, at the boundary: if an earlier
    # same-bar fill has already consumed all available cash, a later
    # symbol's buy must be skipped entirely (not filled with 0 shares),
    # exactly as a broker would reject an order it can't fund at all.
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    t2 = pd.Timestamp("2024-01-08 09:45:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": [t1, t2], "open": [99.0, 100.0], "close": [100.0, 100.0]}),
        "SPY": pd.DataFrame({"time": [t1, t2], "open": [99.0, 100.0], "close": [100.0, 100.0]}),
    }

    def fake_decide_trade(**kwargs):
        return TradeDecision(
            action="buy", reason="test", shares=6, stop_price=1.0, target_price=9999.0
        )

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=600.0)

    symbols_bought = {t["symbol"] for t in result.trades if t["action"] == "buy"}
    assert symbols_bought == {"AAPL"}  # SPY's buy had no cash left to fund it


def test_run_backtest_clamp_preserves_fractional_shares_when_cash_is_not_an_exact_multiple():
    # Same clamp as the two tests above, but the leftover cash ($400) doesn't
    # divide evenly by SPY's price ($120) -- the clamp must keep the
    # fractional remainder (3.3333 shares) instead of flooring it to 3,
    # matching the fractional-share support added to PositionSizer.
    t1 = pd.Timestamp("2024-01-08 09:30:00")
    t2 = pd.Timestamp("2024-01-08 09:45:00")
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": [t1, t2], "open": [99.0, 100.0], "close": [100.0, 100.0]}),
        "SPY": pd.DataFrame({"time": [t1, t2], "open": [99.0, 120.0], "close": [120.0, 120.0]}),
    }

    def fake_decide_trade(**kwargs):
        return TradeDecision(
            action="buy", reason="test", shares=6, stop_price=1.0, target_price=9999.0
        )

    with patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade):
        result = run_backtest(df_by_symbol, starting_equity=1000.0)

    buys_by_symbol = {t["symbol"]: t for t in result.trades if t["action"] == "buy"}
    assert buys_by_symbol["AAPL"]["shares"] == 6  # first mover: 6 @ $100 = $600, leaves $400
    assert buys_by_symbol["SPY"]["shares"] == 3.3333  # $400 / $120 = 3.3333..., not floored to 3


def test_run_backtest_passes_a_confirmation_bars_series_from_volatility_module():
    times = pd.to_datetime([
        "2024-01-08 09:30:00", "2024-01-08 09:45:00", "2024-01-08 10:00:00",
        "2024-01-08 10:15:00", "2024-01-08 10:30:00",
    ])
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": times, "open": [100.0] * 5, "close": [100.0] * 5}),
    }
    with patch("graywind_strategy.backtester.compute_signals", wraps=compute_signals) as mock_compute, \
         patch("graywind_strategy.backtester.decide_trade",
               return_value=TradeDecision(action="hold", reason="no buy signal")):
        run_backtest(df_by_symbol)

    assert mock_compute.call_count == 1
    # 5 bars is far short of both compute_signals' own 30-bar warmup and
    # volatility's 260-bar percentile window -- the point of this test is
    # that run_backtest wires a real per-bar confirmation_bars Series
    # through at all, not what its (all-K=1, here) value works out to.
    assert isinstance(mock_compute.call_args.kwargs["confirmation_bars"], pd.Series)


def test_run_backtest_confirmation_bars_override_disables_filter_for_that_symbol():
    times = pd.to_datetime([
        "2024-01-08 09:30:00", "2024-01-08 09:45:00", "2024-01-08 10:00:00",
        "2024-01-08 10:15:00", "2024-01-08 10:30:00",
    ])
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": times, "open": [100.0] * 5, "close": [100.0] * 5}),
    }
    with patch("graywind_strategy.backtester.compute_signals", wraps=compute_signals) as mock_compute, \
         patch("graywind_strategy.backtester.decide_trade",
               return_value=TradeDecision(action="hold", reason="no buy signal")):
        run_backtest(df_by_symbol, confirmation_bars_override={"AAPL": None})

    assert mock_compute.call_args.kwargs["confirmation_bars"] is None
