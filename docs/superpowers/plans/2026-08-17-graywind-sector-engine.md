# Graywind Sector-Aware Strategy Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retune Graywind's RSI/SMA crossover with a volatility-scaled confirmation-bars filter (fixing the whipsaw pattern found in the sector root-cause analysis) and expand the backtest-only roster to 8 symbols across 3 sectors, without touching signal logic per sector or the live watchlist.

**Architecture:** Two new modules (`graywind_strategy/sector_config.py`, `graywind_strategy/volatility.py`) feed an optional `confirmation_bars` parameter into the existing `strategy_engine.compute_signals()`, consumed at both existing call sites (`backtester.py`, `live_loop.py`). `pipeline.decide_trade()` is untouched — it only ever consumes an already-computed `signal` string.

**Tech Stack:** Python, pandas, `pandas_ta_classic` (already a dependency — same `.ta` accessor already used for RSI/SMA), pytest, `unittest.mock`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md` — read it for full rationale; this plan implements it verbatim plus two gaps this plan discovered while grounding the design in the real code (both resolved with the user before writing this plan, see Tasks 4 and 5).
- TDD (red/green) for every change to `strategy_engine.py`, `volatility.py`, `sector_config.py`, `backtester.py`, `live_loop.py` — this project's standing convention (see `tests/test_backtester.py`'s existing tests). The two new research scripts (Tasks 6–7) follow this repo's existing precedent of *no* test file for one-off fetch/validation scripts (`scripts/fetch_sector_data.py`, `scripts/run_sector_backtest.py` have none either) — verified instead by a `py_compile` syntax check.
- Full test suite: `python3 -m pytest tests/ -q` (145 passing as of `d0adfae`, before this plan's changes — run it after every task, not just at the end).
- `ALPACA_API_KEY`/`ALPACA_API_SECRET` must be passed inline on the same command line as any fetch script invocation (e.g. `ALPACA_API_KEY="..." ALPACA_API_SECRET="..." python3 scripts/fetch_roster_data.py`) — a separate `export` does not persist to the next shell invocation in this harness. Tasks 6–7 note where this applies; actually running the fetch requires real credentials not available in this environment, so those specific commands are for the user/a later session to run, not verifiable here.
- Do not add the roster symbols (XOM/CVX/NVDA/MSFT/JNJ/UNH) to `live_loop.py`'s `WATCHLIST` or `fetch_alpaca_data.py`'s `WATCHLIST` anywhere in this plan — per the design's resolved sequencing, that only happens after backtest validation (Task 7), which is itself out of this plan's scope (a later decision once real data exists).

---

### Task 1: `sector_config.py` — static symbol-to-sector tagging

**Files:**
- Create: `graywind_strategy/sector_config.py`
- Test: `tests/test_sector_config.py`

**Interfaces:**
- Produces: `SYMBOL_SECTOR: dict[str, str]`, `symbols_in_sector(sector: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sector_config.py
from graywind_strategy.sector_config import SYMBOL_SECTOR, symbols_in_sector


def test_symbol_sector_contains_all_roster_symbols():
    for symbol in ["AAPL", "XOM", "CVX", "NVDA", "MSFT", "JNJ", "UNH"]:
        assert symbol in SYMBOL_SECTOR


def test_symbol_sector_excludes_broad_market_spy():
    # SPY is a broad-market index, not sector-specific -- deliberately
    # absent from the mapping rather than tagged with an arbitrary sector.
    assert "SPY" not in SYMBOL_SECTOR


def test_symbols_in_sector_returns_expected_energy_symbols():
    assert sorted(symbols_in_sector("energy")) == ["CVX", "XOM"]


def test_symbols_in_sector_returns_expected_tech_symbols():
    assert sorted(symbols_in_sector("tech")) == ["AAPL", "MSFT", "NVDA"]


def test_symbols_in_sector_returns_empty_list_for_unknown_sector():
    assert symbols_in_sector("nonexistent") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sector_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.sector_config'`

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/sector_config.py
"""Static symbol-to-sector tagging. Sector tags exist for FUTURE
non-volatility caveats (e.g. an energy oil-price gate, a tech
earnings-surprise gate) -- not consumed by graywind_strategy.volatility or
any confirmation-bars math (see
docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md). This
module has no dependents yet; it is scaffolding for later work.
"""

SYMBOL_SECTOR = {
    "AAPL": "tech",
    "NVDA": "tech",
    "MSFT": "tech",
    "XOM": "energy",
    "CVX": "energy",
    "JNJ": "health",
    "UNH": "health",
    # SPY is a broad-market index, not sector-specific -- deliberately
    # left out of this mapping rather than tagged with an arbitrary sector.
}


def symbols_in_sector(sector):
    return [symbol for symbol, tag in SYMBOL_SECTOR.items() if tag == sector]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sector_config.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/sector_config.py tests/test_sector_config.py
git commit -m "Add sector_config.py with the locked-in roster's sector tags"
```

---

### Task 2: `volatility.py` — trailing volatility to confirmation-bars-K

**Files:**
- Create: `graywind_strategy/volatility.py`
- Test: `tests/test_volatility.py`

**Interfaces:**
- Consumes: a `pandas.DataFrame` with `high`/`low`/`close` columns (same OHLC shape `alpaca_data/*.csv`/`data/sector/*.csv` already have).
- Produces: `ATR_PERIOD = 14`, `PERCENTILE_WINDOW = 260`, `compute_atr_pct(df, period=ATR_PERIOD) -> pd.Series`, `confirmation_bars_series(df, atr_period=ATR_PERIOD, percentile_window=PERCENTILE_WINDOW) -> pd.Series[int]` (values in `{1, 2, 3}`, same index as `df`).

**Note found while writing this task (not in the spec):** `pandas_ta_classic`'s `.ta.atr()` does not return a NaN-filled `Series` for insufficient history the way `.ta.rsi()`/`.ta.sma()` do — empirically, on a DataFrame shorter than `period`, it silently returns the raw input DataFrame unchanged (confirmed against pandas 3.0.5 / pandas_ta_classic in this environment). `compute_atr_pct` guards against this explicitly instead of trusting that call for short DataFrames, mirroring `strategy_engine.compute_signals`'s own existing `len(df) < min_bars` guard.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_volatility.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_volatility.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.volatility'`

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/volatility.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_volatility.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/volatility.py tests/test_volatility.py
git commit -m "Add volatility.py: self-relative ATR-percentile confirmation-bars-K"
```

---

### Task 3: `strategy_engine.py` — confirmation-bars filter on `compute_signals`

**Files:**
- Modify: `graywind_strategy/strategy_engine.py`
- Test: `tests/test_strategy_engine.py`

**Interfaces:**
- Consumes: nothing new from Tasks 1–2 (this task is self-contained; `confirmation_bars` is passed in by the *caller*, computed via `volatility.confirmation_bars_series` in Tasks 4–5).
- Produces: `apply_confirmation_filter(df, confirmation_bars, rsi_oversold=RSI_OVERSOLD, rsi_overbought=RSI_OVERBOUGHT) -> pd.Series[str]`; `compute_signals(df, ..., confirmation_bars=None)` — new optional keyword, backward compatible when omitted or `None`. Accepts `None`, a plain `int`, or a per-bar `pd.Series` aligned to `df.index` (raises `ValueError` on a misaligned `Series`).

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_strategy_engine.py (existing imports stay; add this one)
from graywind_strategy.strategy_engine import apply_confirmation_filter


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
```

`tests/test_strategy_engine.py` doesn't currently import `pytest` — add `import pytest` alongside the existing `import random` / `import pandas as pd` at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_strategy_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_confirmation_filter'`

- [ ] **Step 3: Write the implementation**

Replace `graywind_strategy/strategy_engine.py` in full:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_strategy_engine.py -v`
Expected: PASS (all existing tests plus the 6 new ones)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/strategy_engine.py tests/test_strategy_engine.py
git commit -m "Add optional confirmation-bars whipsaw filter to compute_signals"
```

---

### Task 4: Wire `confirmation_bars` into `backtester.py`

**Files:**
- Modify: `graywind_strategy/backtester.py:12-16` (imports), `:76-101` (`run_backtest` signature, docstring, `signals_by_symbol`)
- Test: `tests/test_backtester.py`

**Interfaces:**
- Consumes: `volatility.confirmation_bars_series(df)` (Task 2), `compute_signals(df, confirmation_bars=...)` (Task 3).
- Produces: `run_backtest(..., confirmation_bars_override=None)` — new optional keyword. `confirmation_bars_override` is a `{symbol: value}` dict; symbols present in it use that value (including `None`, to disable filtering) instead of the auto-computed series. This is the supported hook Task 7's validation script uses to run the same backtest with confirmation-bars on vs. off, instead of monkeypatching `volatility`'s internals — same pattern as this function's existing `gates_always_pass` bypass.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_backtester.py`. First add `from graywind_strategy.strategy_engine import compute_signals` to the existing import block at the top of the file (alongside the existing `from graywind_strategy.backtester import ...` and `from graywind_strategy.pipeline import TradeDecision` lines).

```python
def test_run_backtest_passes_a_confirmation_bars_series_from_volatility_module():
    times = pd.to_datetime([
        "2024-01-08 09:30:00", "2024-01-08 09:45:00", "2024-01-08 10:00:00",
        "2024-01-08 10:15:00", "2024-01-08 10:30:00",
    ])
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": times, "open": [100.0] * 5, "close": [100.0] * 5}),
    }
    with patch("graywind_strategy.backtester.compute_signals", wraps=compute_signals) as mock_compute, \
         patch("graywind_strategy.backtester.decide_trade",
               return_value=TradeDecision(action="hold", reason="no buy signal")):
        run_backtest(df_by_symbol)

    assert mock_compute.call_count == 1
    # 5 bars is far short of both compute_signals' own 30-bar warmup and
    # volatility's 260-bar percentile window -- the point of this test is
    # that run_backtest wires a real per-bar confirmation_bars Series
    # through at all, not what its (all-K=1, here) value works out to.
    assert isinstance(mock_compute.call_args.kwargs["confirmation_bars"], pd.Series)


def test_run_backtest_confirmation_bars_override_disables_filter_for_that_symbol():
    times = pd.to_datetime([
        "2024-01-08 09:30:00", "2024-01-08 09:45:00", "2024-01-08 10:00:00",
        "2024-01-08 10:15:00", "2024-01-08 10:30:00",
    ])
    df_by_symbol = {
        "AAPL": pd.DataFrame({"time": times, "open": [100.0] * 5, "close": [100.0] * 5}),
    }
    with patch("graywind_strategy.backtester.compute_signals", wraps=compute_signals) as mock_compute, \
         patch("graywind_strategy.backtester.decide_trade",
               return_value=TradeDecision(action="hold", reason="no buy signal")):
        run_backtest(df_by_symbol, confirmation_bars_override={"AAPL": None})

    assert mock_compute.call_args.kwargs["confirmation_bars"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_backtester.py -v -k confirmation_bars`
Expected: FAIL — `TypeError: run_backtest() got an unexpected keyword argument 'confirmation_bars_override'` (first test fails with an `AssertionError` on `mock_compute.call_args.kwargs` not containing `"confirmation_bars"`, since today's call is positional/unkeyed `compute_signals(df)`)

- [ ] **Step 3: Write the implementation**

In `graywind_strategy/backtester.py`, change the imports block (lines 12–16) from:

```python
from graywind_strategy.pipeline import decide_trade
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.strategy_engine import compute_signals
```

to:

```python
from graywind_strategy import volatility
from graywind_strategy.pipeline import decide_trade
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.strategy_engine import compute_signals
```

Change the `run_backtest` signature, docstring, and `signals_by_symbol` construction (lines 76–101) from:

```python
def run_backtest(df_by_symbol, starting_equity=10000.0,
                  fred_api_key=None, news_client=None, finnhub_api_key=None,
                  gates_always_pass=False):
    """Runs decide_trade() bar-by-bar for every symbol, in timestamp order
    across symbols so PDT/drawdown state is shared correctly. Assumes each
    DataFrame in df_by_symbol already has 'time', 'open', and 'close'
    columns (from Task 5's CSV format).

    A signal or stop/target trigger is only knowable once a bar's close
    prints, so any resulting order is queued rather than filled immediately
    -- it fills at that same symbol's *next* bar's open, the earliest a
    live system reacting to the same close could actually have gotten
    filled. Filling at the same bar's own close (the previous behavior)
    would let the backtest trade at a price it could not have known was
    coming. A trigger on a symbol's last available bar has no following bar
    to fill on and is simply left unfilled.

    `gates_always_pass` is forwarded straight into every decide_trade() call
    below -- the plan-specified, supported way to bypass the vix/sentiment/
    earnings gates for testing/synthetic-data runs (see
    scripts/task11_integration_run.py), instead of monkeypatching
    graywind_strategy.pipeline's internals.
    """
    signals_by_symbol = {
        symbol: compute_signals(df) for symbol, df in df_by_symbol.items()
    }
```

to:

```python
def run_backtest(df_by_symbol, starting_equity=10000.0,
                  fred_api_key=None, news_client=None, finnhub_api_key=None,
                  gates_always_pass=False, confirmation_bars_override=None):
    """Runs decide_trade() bar-by-bar for every symbol, in timestamp order
    across symbols so PDT/drawdown state is shared correctly. Assumes each
    DataFrame in df_by_symbol already has 'time', 'open', and 'close'
    columns (from Task 5's CSV format).

    A signal or stop/target trigger is only knowable once a bar's close
    prints, so any resulting order is queued rather than filled immediately
    -- it fills at that same symbol's *next* bar's open, the earliest a
    live system reacting to the same close could actually have gotten
    filled. Filling at the same bar's own close (the previous behavior)
    would let the backtest trade at a price it could not have known was
    coming. A trigger on a symbol's last available bar has no following bar
    to fill on and is simply left unfilled.

    `gates_always_pass` is forwarded straight into every decide_trade() call
    below -- the plan-specified, supported way to bypass the vix/sentiment/
    earnings gates for testing/synthetic-data runs (see
    scripts/task11_integration_run.py), instead of monkeypatching
    graywind_strategy.pipeline's internals.

    `confirmation_bars_override`, when given, is a `{symbol: value}` dict
    that overrides the auto-computed `volatility.confirmation_bars_series`
    for just the symbols present in it (value can be `None` to disable
    confirmation-bars filtering entirely for that symbol) -- the supported
    way for a research script (scripts/validate_sector_engine.py) to run
    the same backtest with confirmation-bars on vs. off, instead of
    monkeypatching graywind_strategy.volatility's internals. Symbols not
    present in the dict (or when the dict itself is None, the default) use
    the real per-bar volatility-scaled K.
    """
    signals_by_symbol = {}
    for symbol, df in df_by_symbol.items():
        if confirmation_bars_override is not None and symbol in confirmation_bars_override:
            k = confirmation_bars_override[symbol]
        else:
            k = volatility.confirmation_bars_series(df)
        signals_by_symbol[symbol] = compute_signals(df, confirmation_bars=k)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_backtester.py -v`
Expected: PASS (all existing tests plus the 2 new ones — existing fixtures are all under 14 rows, so `volatility.compute_atr_pct`'s length guard from Task 2 returns before ever needing `high`/`low` columns those fixtures don't have; no existing fixture needs changes)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, 147 tests (145 + Task 4's 2 new ones; Tasks 1–3's new test files add their own separately-counted tests already verified in their own steps)

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/backtester.py tests/test_backtester.py
git commit -m "Wire volatility-scaled confirmation-bars into run_backtest"
```

---

### Task 5: Wire `confirmation_bars` into `live_loop.py`

**Files:**
- Modify: `live_loop.py:42` (imports), `:49-59` (`SIGNAL_LOOKBACK`), `:270-273` (per-cycle df construction + `compute_signals` call)
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `volatility.confirmation_bars_series(df)` (Task 2), `compute_signals(df, confirmation_bars=...)` (Task 3).

**Two gaps found while writing this task (not in the spec), both already discussed and resolved with the user:**
1. `live_loop.py`'s per-cycle `df` (`live_loop.py:270-272`) is built with only `time`/`close` — no `high`/`low` — so `volatility.compute_atr_pct` can't run there without adding them. Alpaca's bar objects already carry `.high`/`.low` (see `fetch_alpaca_data.py`'s `write_csv`); this task adds them to the dict comprehension.
2. `SIGNAL_LOOKBACK` was 6 calendar days (~150 bars) — enough for `compute_signals`'s own 30-bar warmup, but short of `confirmation_bars_series`'s 260-bar percentile window, so confirmation-bars would never leave its K=1 fallback in live trading. **Resolved: bump to 15 calendar days**, which comfortably covers 260 bars (~10 trading sessions) with margin for weekends/holidays. RSI/SMA are unaffected — they only ever look at their own trailing 30 bars regardless of how much history is fetched.

- [ ] **Step 1: Write the failing tests**

In `tests/test_live_loop.py`:

1. Update the `_FakeBar` class (around line 366) to also carry `high`/`low` (all 3 call sites construct it as `_FakeBar(100.0, <timestamp>)` with no other args, so giving it sensible defaults here is enough — no call site needs to change):

```python
class _FakeBar:
    def __init__(self, price, ts):
        self.timestamp = ts
        self.close = price
        self.high = price
        self.low = price
```

2. Update all three `patch("live_loop.compute_signals", side_effect=lambda df: df.assign(signal="hold"))` sites (around lines 396, 484, 517) to accept the new keyword argument the real call site will now pass:

```python
patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(signal="hold")),
```

3. Add a new test asserting the live cycle passes `confirmation_bars` through:

```python
def test_process_symbol_cycle_passes_confirmation_bars_to_compute_signals():
    fake_account = MagicMock()
    fake_account.equity = "10000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    def fake_fetch_bars(client, symbol, start, end):
        return [_FakeBar(100.0, datetime(2024, 1, 8, 10, 0, tzinfo=ET))]

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state), \
         patch("live_loop.save_state"), \
         patch("live_loop.fetch_bars", side_effect=fake_fetch_bars), \
         patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(signal="hold")) as mock_compute, \
         patch("live_loop.decide_trade", return_value=TradeDecision(action="hold", reason="no buy signal")), \
         patch("live_loop.write_cycle_export"):
        live_loop.main()

    assert mock_compute.call_count == len(live_loop.WATCHLIST)
    for call in mock_compute.call_args_list:
        assert "confirmation_bars" in call.kwargs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_live_loop.py -v`
Expected: The new test FAILs with `AssertionError` (today's call passes no `confirmation_bars` kwarg); the three updated `lambda df, **kwargs: ...` sites still PASS unchanged since `**kwargs` is a superset-compatible signature — this step's real fail signal is the new test.

- [ ] **Step 3: Write the implementation**

In `live_loop.py`, add the import (line 42 area, alongside the existing `from graywind_strategy.strategy_engine import compute_signals`):

```python
from graywind_strategy import volatility
from graywind_strategy.strategy_engine import compute_signals
```

Replace the `SIGNAL_LOOKBACK` constant and its comment (lines 49–59) with:

```python
# 15 calendar days of 15-min bars (up from 6): the original 6-day figure
# only needed to clear strategy_engine.compute_signals' own 30-bar
# indicator warm-up with a comfortable multi-session margin against
# weekend/holiday gaps (see below) -- volatility.confirmation_bars_series'
# 260-bar trailing percentile window (~10 trading sessions at ~26 bars/
# session) is now the binding constraint. 15 calendar days comfortably
# covers 10+ trading sessions even across a long weekend, so the
# confirmation-bars filter actually leaves its K=1 (unfiltered) fallback
# in live trading instead of running permanently unfiltered.
#
# Original 6-day reasoning, still true as a lower bound: worst case is a
# 3-day weekend+holiday gap (e.g. the Tuesday after MLK Monday, itself
# preceded by a weekend), which still needs to leave 2 full prior trading
# sessions (~52 bars at 26 bars/session) of headroom above the 30-bar
# warm-up strategy_engine.compute_signals requires before it computes a
# real signal (short-frame guard forces "hold" below that). A 3-day
# lookback only spans the tail of one session for most of a Monday
# (pinned at 27 bars all day -- never reaching 30) and the first
# post-holiday session (26 bars), silently forcing every "buy" evaluation
# to "hold" on those days -- indistinguishable in logs from a genuine
# no-signal bar. See final-review Fix 1.
SIGNAL_LOOKBACK = timedelta(days=15)
```

Replace the per-cycle df construction and `compute_signals` call (lines 270–273):

```python
                df = pd.DataFrame([
                    {"time": bar.timestamp, "close": bar.close} for bar in bars
                ])
                df = compute_signals(df)
```

with:

```python
                df = pd.DataFrame([
                    {"time": bar.timestamp, "close": bar.close,
                     "high": bar.high, "low": bar.low}
                    for bar in bars
                ])
                df = compute_signals(df, confirmation_bars=volatility.confirmation_bars_series(df))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_live_loop.py -v`
Expected: PASS (all existing tests plus the 1 new one)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: PASS, 148 tests

- [ ] **Step 6: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "Wire volatility-scaled confirmation-bars into the live cycle; extend SIGNAL_LOOKBACK to 15 days"
```

---

### Task 6: `scripts/fetch_roster_data.py` — fetch the 6 new roster symbols

**Files:**
- Create: `scripts/fetch_roster_data.py`

**Interfaces:**
- Consumes: `fetch_bars`, `write_csv` from `fetch_alpaca_data.py` (already exist, already tested in `tests/test_fetch_alpaca_data.py` — this task reuses them rather than duplicating fetch/write logic).
- Produces: `data/roster/{xom,cvx,nvda,msft,jnj,unh}.csv`, once run with real credentials.

No test file for this task — this repo's existing precedent (`scripts/fetch_sector_data.py`) has none either; `fetch_bars`/`write_csv` are already covered by `tests/test_fetch_alpaca_data.py`. Verified instead by a syntax check.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Fetches historical 15-minute bars for the sector-engine roster expansion
(energy: XOM/CVX, tech: NVDA/MSFT, health: JNJ/UNH -- see
docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md) into
data/roster/, for backtesting and out-of-sample validation.

Deliberately separate from fetch_alpaca_data.py's WATCHLIST (["AAPL", "SPY"])
and live_loop.py's WATCHLIST -- per the design's resolved sequencing, these
symbols reach the live paper-trading watchlist only after they're
backtest-validated, not in the same change that fetches their data.
Requires ALPACA_API_KEY / ALPACA_API_SECRET in the environment.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.historical import StockHistoricalDataClient

from fetch_alpaca_data import fetch_bars, write_csv

ROSTER_SYMBOLS = ["XOM", "CVX", "NVDA", "MSFT", "JNJ", "UNH"]
OUTPUT_DIR = "data/roster"


def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY / ALPACA_API_SECRET not set", file=sys.stderr)
        sys.exit(1)

    client = StockHistoricalDataClient(api_key, api_secret)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)

    for symbol in ROSTER_SYMBOLS:
        try:
            bars = fetch_bars(client, symbol, start, end)
            path = write_csv(symbol, bars, output_dir=OUTPUT_DIR)
            print(f"wrote {len(bars)} bars for {symbol} to {path}")
        except Exception as exc:
            print(f"ERROR fetching {symbol}: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it's syntactically valid and importable**

Run: `python3 -m py_compile scripts/fetch_roster_data.py && python3 -c "import ast; ast.parse(open('scripts/fetch_roster_data.py').read())" && echo OK`
Expected: `OK`, no output from `py_compile`

- [ ] **Step 3: Commit**

```bash
git add scripts/fetch_roster_data.py
git commit -m "Add fetch_roster_data.py for the 6 new sector-roster symbols"
```

*(Actually running this script requires real `ALPACA_API_KEY`/`ALPACA_API_SECRET`, e.g. `ALPACA_API_KEY="..." ALPACA_API_SECRET="..." python3 scripts/fetch_roster_data.py` — not available in this environment; run it in a session that has them before Task 7's script can do anything useful.)*

---

### Task 7: `scripts/validate_sector_engine.py` — out-of-sample validation

**Files:**
- Create: `scripts/validate_sector_engine.py`

**Interfaces:**
- Consumes: `run_backtest(..., confirmation_bars_override=...)` (Task 4), `volatility` (Task 2), and CSVs at `alpaca_data/{aapl,spy}.csv`, `data/sector/{xle,xlk,xlv}.csv` (already exist), `data/roster/{xom,cvx,nvda,msft,jnj,unh}.csv` (Task 6, once fetched with real credentials).

No test file — same precedent as `scripts/run_sector_backtest.py` (also untested; it exercises already-tested `run_backtest` against real CSVs, not a unit of its own logic). Verified by a syntax check plus a smoke run against whatever CSVs already exist in this environment (`alpaca_data/aapl.csv`, `alpaca_data/spy.csv`) — the roster/sector CSVs will print as `SKIPPED` until fetched.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Out-of-sample validation for the sector-aware confirmation-bars engine
(docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md).

Splits each symbol's CSV chronologically -- the last 20% of bars held out
-- and re-runs the hold-time whipsaw breakdown from the original
root-cause analysis (see the spec's "Root cause" section) *only on trades
opened in that held-out window*, comparing short-hold-bucket win rate with
confirmation-bars on vs. off. This is what proves the fix generalizes,
rather than just fitting the data already eyeballed during root-cause
analysis.

The backtest itself runs against each symbol's FULL history, not a
truncated slice -- volatility.confirmation_bars_series needs real trailing
history (up to 260 bars) to leave its K=1 fallback, and truncating the
input df to just the held-out 20% would starve it of that. Only the
*scoring* (which round trips count toward the printed win rates) is
restricted to the held-out window, via each round trip's entry (buy) time.

Requires data/roster/*.csv (scripts/fetch_roster_data.py) and
data/sector/*.csv / alpaca_data/*.csv (scripts/fetch_sector_data.py /
fetch_alpaca_data.py) already fetched -- symbols whose CSV doesn't exist
yet are skipped with a note, not treated as an error.

Run with: python3 scripts/validate_sector_engine.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from graywind_strategy.backtester import run_backtest

HOLDOUT_FRACTION = 0.2

SYMBOLS = {
    "AAPL": "alpaca_data/aapl.csv",
    "SPY": "alpaca_data/spy.csv",
    "XLE": "data/sector/xle.csv",
    "XLK": "data/sector/xlk.csv",
    "XLV": "data/sector/xlv.csv",
    "XOM": "data/roster/xom.csv",
    "CVX": "data/roster/cvx.csv",
    "NVDA": "data/roster/nvda.csv",
    "MSFT": "data/roster/msft.csv",
    "JNJ": "data/roster/jnj.csv",
    "UNH": "data/roster/unh.csv",
}


def held_out_cutoff_time(df, holdout_fraction=HOLDOUT_FRACTION):
    split_index = int(len(df) * (1 - holdout_fraction))
    return df["time"].iloc[split_index]


def hold_time_bucket_win_rates(trades, entries_at_or_after):
    """Pairs buy/sell round trips (same technique as
    graywind_strategy.backtester.win_rate), keeping only round trips whose
    entry (buy) time is at or after `entries_at_or_after`, then splits
    those into <1 day hold vs >=1 day hold buckets. Returns
    (short_hold_win_rate_or_None, short_hold_count,
     long_hold_win_rate_or_None, long_hold_count).
    """
    round_trips = []
    open_by_symbol = {}
    for trade in trades:
        symbol = trade["symbol"]
        if trade["action"] == "buy":
            open_by_symbol[symbol] = trade
        elif trade["action"] == "sell":
            opened = open_by_symbol.pop(symbol, None)
            if opened is not None and opened["time"] >= entries_at_or_after:
                hold_time = trade["time"] - opened["time"]
                round_trips.append((hold_time, trade["price"] > opened["price"]))

    short = [win for hold_time, win in round_trips if hold_time.total_seconds() < 86400]
    long = [win for hold_time, win in round_trips if hold_time.total_seconds() >= 86400]

    short_win_rate = sum(short) / len(short) if short else None
    long_win_rate = sum(long) / len(long) if long else None
    return short_win_rate, len(short), long_win_rate, len(long)


def format_rate(rate):
    return f"{rate:.1%}" if rate is not None else "n/a"


def main():
    print(f"{'symbol':<8}{'filter':<8}{'short_n':>9}{'short_win':>11}{'long_n':>9}{'long_win':>11}")
    for symbol, path in SYMBOLS.items():
        try:
            df = pd.read_csv(path, parse_dates=["time"])
        except FileNotFoundError:
            print(f"{symbol:<8}SKIPPED (no CSV at {path} -- run the matching fetch script first)")
            continue

        cutoff = held_out_cutoff_time(df)

        for label, override in (("off", {symbol: None}), ("on", None)):
            result = run_backtest(
                {symbol: df}, starting_equity=10000.0, gates_always_pass=True,
                confirmation_bars_override=override,
            )
            short_win, short_n, long_win, long_n = hold_time_bucket_win_rates(result.trades, cutoff)
            print(
                f"{symbol:<8}{label:<8}{short_n:>9}{format_rate(short_win):>11}"
                f"{long_n:>9}{format_rate(long_win):>11}"
            )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it's syntactically valid**

Run: `python3 -m py_compile scripts/validate_sector_engine.py && echo OK`
Expected: `OK`

- [ ] **Step 3: Smoke-run it against whatever CSVs already exist**

Run: `python3 scripts/validate_sector_engine.py`
Expected: A table with one `off`/`on` row pair per symbol whose CSV exists in this environment (`AAPL`, `SPY` at minimum, from earlier sessions' fetches), `SKIPPED` lines for `XLE`/`XLK`/`XLV`/roster symbols not yet fetched, no traceback.

- [ ] **Step 4: Commit**

```bash
git add scripts/validate_sector_engine.py
git commit -m "Add validate_sector_engine.py: out-of-sample confirmation-bars on/off comparison"
```

---

## After Task 7

All 7 tasks land the full design from `docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md`. What's still open, deliberately out of this plan's scope:

- Actually running `scripts/fetch_roster_data.py` and `scripts/fetch_sector_data.py` with real credentials, then `scripts/validate_sector_engine.py`, to get a real out-of-sample verdict — needs a session with `ALPACA_API_KEY`/`ALPACA_API_SECRET`.
- Adding the roster symbols to `live_loop.py`'s `WATCHLIST` — per the resolved sequencing, only after that validation run looks good.
- Live cron verification and GitHub Actions secret confirmation — unrelated, carried-forward thread, untouched by this plan.
