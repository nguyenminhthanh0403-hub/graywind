"""Per-symbol trailing volatility -> confirmation-bars count K, used to
retune graywind_strategy.strategy_engine.compute_signals's whipsaw filter
per symbol (see
docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md).
Self-relative percentile ranking, not fixed absolute ATR% cutoffs, so each
symbol's own trailing history sets its own scale -- no per-symbol tuning
needed. No dependency on sector_config.py.
"""
import pandas as pd
import pandas_ta_classic  # noqa: F401  (registers the .ta accessor on DataFrame)

ATR_PERIOD = 14
PERCENTILE_WINDOW = 260  # ~10 trading days at 26 15-minute bars/day


def compute_atr_pct(df, period=ATR_PERIOD):
    """ATR(period) as a percentage of close price. Trailing/causal by
    construction -- bar i only ever depends on bars <= i.
    """
    if len(df) < period:
        # pandas_ta_classic's .ta.atr() doesn't return NaN for
        # insufficient history the way .ta.rsi()/.ta.sma() do -- it
        # silently returns the raw input DataFrame unchanged. Guard
        # explicitly instead of trusting that call for short DataFrames.
        return pd.Series(float("nan"), index=df.index)
    atr = df.ta.atr(length=period)
    close = df["close"]
    atr_pct = (atr / close) * 100
    return atr_pct.where(close > 0)  # non-positive close -> NaN, not inf


def confirmation_bars_series(df, atr_period=ATR_PERIOD, percentile_window=PERCENTILE_WINDOW):
    """Per-bar confirmation-bars count K in {1, 2, 3}, ranking each bar's
    ATR% against that same symbol's own trailing `percentile_window` bars.
    Bottom third -> K=1, middle third -> K=2, top third -> K=3. Bars
    without enough history for the ATR period or the percentile window
    default to K=1 (today's unfiltered behavior) -- safe, since
    strategy_engine.compute_signals already treats early bars as "hold"
    regardless of K.
    """
    atr_pct = compute_atr_pct(df, period=atr_period)
    percentile_rank = atr_pct.rolling(window=percentile_window, min_periods=percentile_window).rank(pct=True)
    return percentile_rank.apply(_bucket_to_k).astype(int)


def _bucket_to_k(percentile):
    if pd.isna(percentile):
        return 1
    if percentile <= 1 / 3:
        return 1
    if percentile <= 2 / 3:
        return 2
    return 3
