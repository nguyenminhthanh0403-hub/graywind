import random

import pandas as pd
import pytest

from graywind_strategy.strategy_engine import compute_signals, evaluate_signal, apply_confirmation_filter


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


def test_compute_signals_confirmation_bars_none_matches_omitting_it():
    df = pd.DataFrame({"close": [100 + i * 0.5 for i in range(40)]})
    assert compute_signals(df, confirmation_bars=None)["signal"].equals(
        compute_signals(df)["signal"]
    )


def test_apply_confirmation_filter_holds_an_isolated_single_bar_condition():
    # rsi=20 (oversold) keeps sell_condition false throughout, isolating
    # this test to buy-side filtering only. buy_condition is true only at
    # index 1 (fast > slow there, false everywhere else) -- K=2 requires
    # it to hold for 2 consecutive bars, so it should never fire.
    df = pd.DataFrame({
        "rsi": [20, 20, 20, 20],
        "sma_fast": [95, 105, 95, 95],
        "sma_slow": [100, 100, 100, 100],
    })
    result = apply_confirmation_filter(df, confirmation_bars=2, rsi_oversold=30, rsi_overbought=70)
    assert list(result) == ["hold", "hold", "hold", "hold"]


def test_apply_confirmation_filter_fires_only_on_the_kth_consecutive_confirmed_bar():
    df = pd.DataFrame({
        "rsi": [20, 20, 20, 20],
        "sma_fast": [95, 105, 106, 107],  # buy_condition: F, T, T, T
        "sma_slow": [100, 100, 100, 100],
    })
    result = apply_confirmation_filter(df, confirmation_bars=3, rsi_oversold=30, rsi_overbought=70)
    assert list(result) == ["hold", "hold", "hold", "buy"]


def test_apply_confirmation_filter_uses_each_bars_own_k_from_a_series():
    df = pd.DataFrame({
        "rsi": [20, 20, 20, 20],
        "sma_fast": [105, 105, 105, 105],  # buy_condition true at every bar
        "sma_slow": [100, 100, 100, 100],
    })
    k = pd.Series([1, 3, 3, 3], index=df.index)
    result = apply_confirmation_filter(df, confirmation_bars=k, rsi_oversold=30, rsi_overbought=70)
    # index 0: K=1, fires immediately. index 1: K=3, only 2 bars of history
    # so far -- not confirmed. index 2: K=3, 3 bars of history (0,1,2), all
    # true -- confirmed. index 3: K=3, confirmed.
    assert list(result) == ["buy", "hold", "buy", "buy"]


def test_apply_confirmation_filter_raises_on_misaligned_series_index():
    df = pd.DataFrame({
        "rsi": [20, 20, 20], "sma_fast": [105, 105, 105], "sma_slow": [100, 100, 100],
    })
    k = pd.Series([1, 1, 1], index=[10, 20, 30])  # doesn't match df's default 0,1,2 index
    with pytest.raises(ValueError):
        apply_confirmation_filter(df, confirmation_bars=k, rsi_oversold=30, rsi_overbought=70)
