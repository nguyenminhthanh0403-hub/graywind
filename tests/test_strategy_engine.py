import random

import pandas as pd

from graywind_strategy.strategy_engine import compute_signals, evaluate_signal


def test_evaluate_signal_buy_when_fast_above_slow_and_not_overbought():
    assert evaluate_signal(rsi_value=50, fast_value=105, slow_value=100) == "buy"


def test_evaluate_signal_sell_when_fast_below_slow_and_not_oversold():
    assert evaluate_signal(rsi_value=50, fast_value=95, slow_value=100) == "sell"


def test_evaluate_signal_hold_when_overbought_blocks_a_buy():
    assert evaluate_signal(rsi_value=75, fast_value=105, slow_value=100) == "hold"


def test_evaluate_signal_hold_when_oversold_blocks_a_sell():
    assert evaluate_signal(rsi_value=25, fast_value=95, slow_value=100) == "hold"


def test_evaluate_signal_hold_on_missing_indicator_values():
    assert evaluate_signal(rsi_value=float("nan"), fast_value=105, slow_value=100) == "hold"


def test_compute_signals_adds_expected_columns_and_does_not_raise():
    # 40 bars of a simple uptrend is enough to warm up a 30-period SMA.
    df = pd.DataFrame({
        "close": [100 + i * 0.5 for i in range(40)],
    })
    result = compute_signals(df)
    assert list(result.columns) == ["close", "rsi", "sma_fast", "sma_slow", "signal"]
    # The last row has enough history for every indicator to be ready.
    assert result["signal"].iloc[-1] in {"buy", "sell", "hold"}
    assert not pd.isna(result["rsi"].iloc[-1])


def test_compute_signals_with_insufficient_bars_returns_all_hold_without_raising():
    df = pd.DataFrame({"close": [100.0, 101.0, 99.5]})  # far fewer than 30 rows
    result = compute_signals(df)
    assert (result["signal"] == "hold").all()
    assert list(result.columns) == ["close", "rsi", "sma_fast", "sma_slow", "signal"]


def test_compute_signals_produces_both_buy_and_sell_signals_on_an_oscillating_series():
    random.seed(42)
    price = 100.0
    closes = []
    for _ in range(150):
        price += random.uniform(-1.0, 1.0)
        closes.append(price)
    df = pd.DataFrame({"close": closes})
    result = compute_signals(df)
    signals_after_warmup = set(result["signal"].iloc[30:])
    assert "buy" in signals_after_warmup
    assert "sell" in signals_after_warmup
