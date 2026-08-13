"""Rule-based RSI + moving-average crossover signal, computed on a plain
pandas DataFrame via pandas-ta-classic. Same thresholds as the original
LEAN-era design: RSI period 14, fast SMA 10, slow SMA 30, oversold 30,
overbought 70.
"""
import math

import pandas as pd
import pandas_ta_classic  # noqa: F401  (registers the .ta accessor on DataFrame)

RSI_PERIOD = 14
FAST_SMA_PERIOD = 10
SLOW_SMA_PERIOD = 30
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


def evaluate_signal(rsi_value, fast_value, slow_value,
                     rsi_oversold=RSI_OVERSOLD, rsi_overbought=RSI_OVERBOUGHT):
    if any(v is None or (isinstance(v, float) and math.isnan(v))
           for v in (rsi_value, fast_value, slow_value)):
        return "hold"
    if fast_value > slow_value and rsi_value < rsi_overbought:
        return "buy"
    if fast_value < slow_value and rsi_value > rsi_oversold:
        return "sell"
    return "hold"


def compute_signals(df, rsi_period=RSI_PERIOD, fast_period=FAST_SMA_PERIOD,
                     slow_period=SLOW_SMA_PERIOD, rsi_oversold=RSI_OVERSOLD,
                     rsi_overbought=RSI_OVERBOUGHT):
    df = df.copy()
    min_bars = max(rsi_period, fast_period, slow_period)
    if len(df) < min_bars:
        df["rsi"] = float("nan")
        df["sma_fast"] = float("nan")
        df["sma_slow"] = float("nan")
        df["signal"] = "hold"
        return df
    df["rsi"] = df.ta.rsi(length=rsi_period)
    df["sma_fast"] = df.ta.sma(length=fast_period)
    df["sma_slow"] = df.ta.sma(length=slow_period)
    df["signal"] = df.apply(
        lambda row: evaluate_signal(
            row["rsi"], row["sma_fast"], row["sma_slow"], rsi_oversold, rsi_overbought
        ),
        axis=1,
    )
    return df
