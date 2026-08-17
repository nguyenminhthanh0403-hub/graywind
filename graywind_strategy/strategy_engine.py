"""Rule-based RSI + moving-average crossover signal, computed on a plain
pandas DataFrame via pandas-ta-classic. Same thresholds as the original
LEAN-era design: RSI period 14, fast SMA 10, slow SMA 30, oversold 30,
overbought 70. An optional confirmation-bars filter (see
docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md)
requires a crossover to hold for K consecutive bars before it fires, to
retune out whipsaw entries on higher-volatility symbols.
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


def apply_confirmation_filter(df, confirmation_bars, rsi_oversold=RSI_OVERSOLD,
                               rsi_overbought=RSI_OVERBOUGHT):
    """Requires the underlying buy/sell condition to hold for K consecutive
    bars (K taken from `confirmation_bars`, per-bar) before it fires,
    instead of firing on the first bar a crossover appears -- the whipsaw
    fix from the sector-engine design. `df` must already have
    `sma_fast`/`sma_slow`/`rsi` columns (as compute_signals produces).

    `confirmation_bars` is an int (fixed K for every bar) or a per-bar
    Series aligned to `df.index` (the real path -- see
    graywind_strategy.volatility.confirmation_bars_series). A Series whose
    index doesn't match `df.index` raises ValueError -- that's a caller
    bug, not a market-data edge case.
    """
    if isinstance(confirmation_bars, int):
        k_series = pd.Series(confirmation_bars, index=df.index)
    else:
        k_series = confirmation_bars
        if not k_series.index.equals(df.index):
            raise ValueError("confirmation_bars index must match df.index")

    buy_condition = (df["sma_fast"] > df["sma_slow"]) & (df["rsi"] < rsi_overbought)
    sell_condition = (df["sma_fast"] < df["sma_slow"]) & (df["rsi"] > rsi_oversold)

    unique_ks = sorted(set(int(k) for k in k_series))
    buy_confirmed_by_k = {
        k: buy_condition.astype(int).rolling(window=k, min_periods=k).min().eq(1)
        for k in unique_ks
    }
    sell_confirmed_by_k = {
        k: sell_condition.astype(int).rolling(window=k, min_periods=k).min().eq(1)
        for k in unique_ks
    }

    signals = []
    for i in range(len(df)):
        k = int(k_series.iloc[i])
        if buy_confirmed_by_k[k].iloc[i]:
            signals.append("buy")
        elif sell_confirmed_by_k[k].iloc[i]:
            signals.append("sell")
        else:
            signals.append("hold")
    return pd.Series(signals, index=df.index)


def compute_signals(df, rsi_period=RSI_PERIOD, fast_period=FAST_SMA_PERIOD,
                     slow_period=SLOW_SMA_PERIOD, rsi_oversold=RSI_OVERSOLD,
                     rsi_overbought=RSI_OVERBOUGHT, confirmation_bars=None):
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
    if confirmation_bars is not None:
        df["signal"] = apply_confirmation_filter(df, confirmation_bars, rsi_oversold, rsi_overbought)
    return df
