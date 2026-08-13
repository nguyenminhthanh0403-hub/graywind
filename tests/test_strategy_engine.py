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
