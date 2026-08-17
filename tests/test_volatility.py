import pandas as pd

from graywind_strategy.volatility import compute_atr_pct, confirmation_bars_series


def _ohlc(closes, spread=1.0):
    return pd.DataFrame({
        "high": [c + spread for c in closes],
        "low": [c - spread for c in closes],
        "close": closes,
    })


def test_compute_atr_pct_returns_nan_series_for_insufficient_history():
    df = _ohlc([100.0, 101.0, 99.0])  # 3 rows, far fewer than ATR_PERIOD=14
    result = compute_atr_pct(df)
    assert len(result) == 3
    assert result.isna().all()


def test_compute_atr_pct_is_non_negative_once_warmed_up():
    df = _ohlc([100.0 + i * 0.1 for i in range(20)])
    result = compute_atr_pct(df)
    warmed_up = result.dropna()
    assert len(warmed_up) > 0
    assert (warmed_up >= 0).all()


def test_compute_atr_pct_is_nan_not_inf_for_non_positive_close():
    df = _ohlc([100.0] * 20)
    df.loc[19, "close"] = 0.0
    result = compute_atr_pct(df)
    assert pd.isna(result.iloc[-1])


def test_compute_atr_pct_and_confirmation_bars_series_degrade_safely_when_high_low_missing():
    # Enough rows to clear ATR_PERIOD, but no high/low columns -- must
    # degrade to the same safe fallback as insufficient history (all-NaN
    # from compute_atr_pct, all-K=1 from confirmation_bars_series built on
    # top of it), not raise. pandas_ta_classic's .ta.atr() silently no-ops
    # instead of erroring on missing columns, and without this guard the
    # downstream percentile-rank/bucketing logic raises a confusing
    # "truth value of a Series is ambiguous" ValueError instead.
    df = pd.DataFrame({"close": [100.0 + i * 0.1 for i in range(20)]})

    atr_result = compute_atr_pct(df)
    assert len(atr_result) == 20
    assert atr_result.isna().all()

    k_result = confirmation_bars_series(df)
    assert (k_result == 1).all()


def test_confirmation_bars_series_defaults_to_k1_below_percentile_window():
    df = _ohlc([100.0 + i * 0.1 for i in range(50)])  # fewer than PERCENTILE_WINDOW=260
    result = confirmation_bars_series(df)
    assert (result == 1).all()


def test_confirmation_bars_series_rises_in_a_higher_volatility_segment():
    # 40 tight-range bars, then 40 wide-range bars -- a small
    # percentile_window (20) so the test doesn't need 260+ rows to see the
    # window fully filled in both regimes.
    low_vol_closes = [100.0 + (i % 2) * 0.05 for i in range(40)]
    high_vol_closes = [100.0 + (i % 2) * 5.0 for i in range(40)]
    df = pd.concat([
        _ohlc(low_vol_closes, spread=0.5),
        _ohlc(high_vol_closes, spread=5.0),
    ], ignore_index=True)

    result = confirmation_bars_series(df, atr_period=5, percentile_window=20)

    # bars 20:40 -- window fully inside the low-volatility regime.
    # bars 60:80 -- window fully inside the high-volatility regime.
    assert result.iloc[60:80].mean() > result.iloc[20:40].mean()
