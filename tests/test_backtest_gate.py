from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from graywind_strategy.backtest_gate import (
    MIN_HISTORY_DAYS, check_fold_thresholds, fetch_backtest_bars, split_into_folds,
)
from graywind_strategy.backtester import BacktestResult
from graywind_strategy.guardrails import GuardrailViolation


def _fake_bar(ts, price=100.0, volume=1000):
    bar = MagicMock()
    bar.timestamp = ts
    bar.open = price
    bar.high = price + 1
    bar.low = price - 1
    bar.close = price
    bar.volume = volume
    return bar


def test_fetch_backtest_bars_raises_when_no_bars_returned():
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.backtest_gate.fetch_bars",
            lambda client, symbol, start, end: [],
        )
        with pytest.raises(GuardrailViolation, match="no historical bars"):
            fetch_backtest_bars(fake_data_client, "SERV")


def test_fetch_backtest_bars_raises_when_span_below_minimum_history():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    bars = [_fake_bar(start + timedelta(days=d)) for d in range(0, 100, 10)]  # ~90 days span
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.backtest_gate.fetch_bars",
            lambda client, symbol, start, end: bars,
        )
        with pytest.raises(GuardrailViolation, match=f"at least {MIN_HISTORY_DAYS}"):
            fetch_backtest_bars(fake_data_client, "SERV")


def test_fetch_backtest_bars_returns_dataframe_when_span_clears_minimum():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = [_fake_bar(start + timedelta(days=d), price=100.0 + d) for d in range(0, 900, 5)]
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.backtest_gate.fetch_bars",
            lambda client, symbol, start, end: bars,
        )
        df = fetch_backtest_bars(fake_data_client, "SERV")

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]
    assert len(df) == len(bars)
    assert df["close"].iloc[-1] == bars[-1].close


def test_split_into_folds_divides_evenly_when_divisible():
    df = pd.DataFrame({"time": pd.date_range("2020-01-01", periods=100, freq="15min")})
    folds = split_into_folds(df, n_folds=4)
    assert [len(f) for f in folds] == [25, 25, 25, 25]


def test_split_into_folds_gives_remainder_to_last_fold():
    df = pd.DataFrame({"time": pd.date_range("2020-01-01", periods=101, freq="15min")})
    folds = split_into_folds(df, n_folds=4)
    assert [len(f) for f in folds] == [25, 25, 25, 26]


def test_split_into_folds_covers_every_row_exactly_once_in_order():
    df = pd.DataFrame({"value": range(37)})
    folds = split_into_folds(df, n_folds=4)
    reassembled = pd.concat(folds, ignore_index=True)
    assert reassembled["value"].tolist() == list(range(37))


def _passing_result(**overrides):
    defaults = dict(
        equity_curve=[10000.0, 10100.0], trades=[{"x": 1}] * 30,
        sharpe=1.5, max_drawdown=0.10, win_rate=0.50, pdt_compliant=True,
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


def test_check_fold_thresholds_passes_when_every_metric_clears():
    check_fold_thresholds(_passing_result(), fold_index=0)  # no exception == pass


def test_check_fold_thresholds_rejects_low_sharpe():
    with pytest.raises(GuardrailViolation, match="fold 2.*sharpe"):
        check_fold_thresholds(_passing_result(sharpe=0.5), fold_index=2)


def test_check_fold_thresholds_rejects_excessive_drawdown():
    with pytest.raises(GuardrailViolation, match="fold 1.*drawdown"):
        check_fold_thresholds(_passing_result(max_drawdown=0.30), fold_index=1)


def test_check_fold_thresholds_rejects_low_win_rate():
    with pytest.raises(GuardrailViolation, match="fold 0.*win rate"):
        check_fold_thresholds(_passing_result(win_rate=0.30), fold_index=0)


def test_check_fold_thresholds_rejects_too_few_trades():
    with pytest.raises(GuardrailViolation, match="fold 3.*trades"):
        check_fold_thresholds(_passing_result(trades=[{"x": 1}] * 10), fold_index=3)
