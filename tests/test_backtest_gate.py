from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pandas as pd
import pytest

from graywind_strategy.backtest_gate import MIN_HISTORY_DAYS, fetch_backtest_bars
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
