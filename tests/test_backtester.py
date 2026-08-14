from unittest.mock import patch

import pandas as pd

from graywind_strategy.backtester import max_drawdown, run_backtest, sharpe_ratio, win_rate
from graywind_strategy.pipeline import TradeDecision


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
        "AAPL": pd.DataFrame({"time": [t1], "close": [100.0]}),
        "SPY": pd.DataFrame({"time": [t1], "close": [50.0]}),
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
