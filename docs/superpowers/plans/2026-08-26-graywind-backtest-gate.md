# Graywind Backtest Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a required historical-backtest gate — a 4-fold regime-robustness check plus a
Deflated Sharpe Ratio anti-cherry-picking check — that a new tier-2/3 symbol must clear on top
of the existing market-cap/volume/sector guardrail before it can be added to `SYMBOL_TIER`.

**Architecture:** A new module, `graywind_strategy/backtest_gate.py`, fetches the symbol's
available 15-minute-bar history, runs the existing `backtester.run_backtest()` once over the
full period and once per fold (4 sequential, non-overlapping folds), checks fixed thresholds
per fold, and computes a Deflated Sharpe Ratio corrected for a persisted, never-reset trial
counter. `tier_config.validate_symbol_addition()` calls it last, after its existing checks.
`GuardrailViolation` moves to a new shared `graywind_strategy/guardrails.py` module first, to
avoid a circular import between `tier_config` and `backtest_gate`.

**Tech Stack:** Python 3.14, pandas (bar data), stdlib `statistics.NormalDist` for the
DSR/PSR normal-distribution math (no scipy/numpy dependency added — this project doesn't have
scipy installed and the existing backtester already does its own stats by hand with
`statistics`), stdlib `json` for the trial log, `pytest` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-08-26-graywind-backtest-gate-design.md`

## Global Constraints

- TDD: every function gets a failing test written first, per this project's existing convention
  for `backtester.py`/`pipeline.py`/`gates/`/`tier_config.py`.
- All test fixtures are synthetic — no real market data or real API calls in tests. Mock
  `data_client`/`fetch_bars`/`run_backtest` the same way `tests/test_tier_config.py` and
  `tests/test_backtester.py` already do.
- Every rejection raises `GuardrailViolation` (imported from the new `graywind_strategy/
  guardrails.py`, not redefined) naming the exact check and number that failed.
- Full test suite command: `.venv/bin/python -m pytest tests/ -q` (must stay green after every
  task).
- Backtest runs inside the gate use `gates_always_pass=True`, matching the existing precedent
  in `scripts/run_sector_backtest.py` — this repo has no historical VIX/news/earnings data
  wired up to replay the real gates bar-by-bar across years of history.
- DSR math operates on the **per-period, non-annualized** Sharpe ratio computed directly from
  the equity curve — never on `BacktestResult.sharpe`, which is already annualized via
  `PERIODS_PER_YEAR_15MIN` and would corrupt the DSR formula if passed in directly.
- Every call to `validate_symbol_backtest()` appends exactly one row to the trial log, whether
  it passes or fails — including a data-floor failure before any backtest ran (logged with
  `sharpe: null`) — per the spec's literal "every symbol run through this gate" wording. This
  is a deliberate reading of a spec ambiguity, flagged to the user in the plan handoff.

---

## Task 1: Extract `GuardrailViolation` into a shared module

**Why first:** `tier_config.py` will need to call into `backtest_gate.py`, and
`backtest_gate.py` needs to raise the same `GuardrailViolation` class `tier_config.py`'s
existing tests already catch. Keeping the class defined only in `tier_config.py` would force
`backtest_gate.py` to import from `tier_config`, which imports `backtest_gate` — a cycle. This
task is a pure refactor: no behavior change, existing tests must pass unmodified.

**Files:**
- Create: `graywind_strategy/guardrails.py`
- Modify: `graywind_strategy/tier_config.py:1-30` (remove the inline class, import it instead)
- Test: `tests/test_tier_config.py` (existing tests only — no new test needed for this task,
  see Step 2)

**Interfaces:**
- Produces: `graywind_strategy.guardrails.GuardrailViolation` (exception class, no fields)

- [ ] **Step 1: Create the shared module**

```python
# graywind_strategy/guardrails.py
"""Shared guardrail-violation exception. Lives outside tier_config.py and
backtest_gate.py specifically so both can raise/catch the same class without
importing each other -- tier_config calls into backtest_gate, so the reverse
import would be circular.
"""


class GuardrailViolation(Exception):
    pass
```

- [ ] **Step 2: Update `tier_config.py` to import instead of define it**

In `graywind_strategy/tier_config.py`, remove:

```python
class GuardrailViolation(Exception):
    pass
```

Add near the top, with the other imports:

```python
from graywind_strategy.guardrails import GuardrailViolation
```

`GuardrailViolation` stays importable as `from graywind_strategy.tier_config import
GuardrailViolation` (existing tests use this) because it's now a name in `tier_config`'s
namespace via the import, pointing at the exact same class object.

- [ ] **Step 3: Run the full existing test suite to confirm nothing broke**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, same count as before this change (this is a pure refactor — no new tests yet).

- [ ] **Step 4: Commit**

```bash
git add graywind_strategy/guardrails.py graywind_strategy/tier_config.py
git commit -m "refactor: extract GuardrailViolation into its own module

Avoids a circular import between tier_config.py and the upcoming
backtest_gate.py, which both need to raise/catch this exception."
```

---

## Task 2: Historical bar fetch + minimum-history floor

**Files:**
- Create: `graywind_strategy/backtest_gate.py`
- Test: `tests/test_backtest_gate.py`

**Interfaces:**
- Consumes: `fetch_alpaca_data.fetch_bars(client, symbol, start, end)` (existing, returns a
  list of bar objects with `.timestamp`/`.open`/`.high`/`.low`/`.close`/`.volume`),
  `graywind_strategy.guardrails.GuardrailViolation` (Task 1)
- Produces: `fetch_backtest_bars(data_client, symbol, lookback_years=10) -> pandas.DataFrame`
  with columns `time`/`open`/`high`/`low`/`close`/`volume`, sorted ascending by `time` (bars
  come back from Alpaca already in ascending order, unchanged here). Raises
  `GuardrailViolation` if no bars are returned or the span is under `MIN_HISTORY_DAYS`.
  `MIN_HISTORY_DAYS = 730` (module-level constant later tasks also reference).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backtest_gate.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` (`graywind_strategy.backtest_gate`
doesn't exist yet).

- [ ] **Step 3: Create `backtest_gate.py` with the fetch + floor logic**

```python
# graywind_strategy/backtest_gate.py
"""Historical-backtest gate a new tier-2/3 symbol must clear before it can be
added to SYMBOL_TIER, on top of tier_config.py's market-cap/volume/sector
guardrail (docs/superpowers/specs/2026-08-26-graywind-backtest-gate-design.md).
"""
import json
import math
import os
import statistics
from datetime import datetime, timedelta, timezone
from statistics import NormalDist

import pandas as pd

from fetch_alpaca_data import fetch_bars
from graywind_strategy.backtester import run_backtest
from graywind_strategy.guardrails import GuardrailViolation

MIN_HISTORY_DAYS = 730
MIN_TOTAL_TRADES = 300
N_FOLDS = 4
FOLD_MIN_SHARPE = 1.0
FOLD_MAX_DRAWDOWN = 0.25
FOLD_MIN_WIN_RATE = 0.45
FOLD_MIN_TRADES = 30
DSR_THRESHOLD = 0.95

TRIAL_LOG_PATH = os.path.join(os.path.dirname(__file__), "backtest_gate_trials.json")

_EULER_MASCHERONI = 0.5772156649015329
_STANDARD_NORMAL = NormalDist()


def _bars_to_dataframe(bars):
    return pd.DataFrame({
        "time": [pd.Timestamp(bar.timestamp) for bar in bars],
        "open": [bar.open for bar in bars],
        "high": [bar.high for bar in bars],
        "low": [bar.low for bar in bars],
        "close": [bar.close for bar in bars],
        "volume": [bar.volume for bar in bars],
    })


def fetch_backtest_bars(data_client, symbol, lookback_years=10):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * lookback_years)
    bars = fetch_bars(data_client, symbol, start, end)
    if not bars:
        raise GuardrailViolation(
            f"no historical bars returned for {symbol}, cannot run backtest gate"
        )
    df = _bars_to_dataframe(bars)
    span_days = (df["time"].iloc[-1] - df["time"].iloc[0]).days
    if span_days < MIN_HISTORY_DAYS:
        raise GuardrailViolation(
            f"{symbol} has only {span_days} days of history, backtest gate requires "
            f"at least {MIN_HISTORY_DAYS}"
        )
    return df
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/backtest_gate.py tests/test_backtest_gate.py
git commit -m "feat: add backtest gate history fetch + minimum-history floor"
```

---

## Task 3: Fold splitting

**Files:**
- Modify: `graywind_strategy/backtest_gate.py`
- Test: `tests/test_backtest_gate.py`

**Interfaces:**
- Consumes: a `pandas.DataFrame` (Task 2's `fetch_backtest_bars` output shape)
- Produces: `split_into_folds(df, n_folds=N_FOLDS) -> list[pandas.DataFrame]` — exactly
  `n_folds` non-overlapping, sequential slices covering every row of `df` exactly once, each
  re-indexed from 0. All folds get `len(df) // n_folds` rows except the last, which absorbs
  the remainder.

- [ ] **Step 1: Write the failing tests**

```python
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
```

Add `from graywind_strategy.backtest_gate import split_into_folds` (and keep the Task 2 import)
to the top of `tests/test_backtest_gate.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'split_into_folds'`

- [ ] **Step 3: Implement `split_into_folds`**

Add to `graywind_strategy/backtest_gate.py`:

```python
def split_into_folds(df, n_folds=N_FOLDS):
    df = df.reset_index(drop=True)
    fold_size = len(df) // n_folds
    folds = []
    start = 0
    for i in range(n_folds):
        end = start + fold_size if i < n_folds - 1 else len(df)
        folds.append(df.iloc[start:end].reset_index(drop=True))
        start = end
    return folds
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/backtest_gate.py tests/test_backtest_gate.py
git commit -m "feat: add sequential fold splitting for the backtest gate"
```

---

## Task 4: Per-fold threshold checking

**Files:**
- Modify: `graywind_strategy/backtest_gate.py`
- Test: `tests/test_backtest_gate.py`

**Interfaces:**
- Consumes: `graywind_strategy.backtester.BacktestResult` (existing dataclass: `equity_curve`,
  `trades`, `sharpe`, `max_drawdown`, `win_rate`, `pdt_compliant`)
- Produces: `check_fold_thresholds(result, fold_index)` — raises `GuardrailViolation` naming
  `fold_index` and the failing metric if `result.sharpe < FOLD_MIN_SHARPE`,
  `result.max_drawdown > FOLD_MAX_DRAWDOWN`, `result.win_rate < FOLD_MIN_WIN_RATE`, or
  `len(result.trades) < FOLD_MIN_TRADES`. No return value on success.

- [ ] **Step 1: Write the failing tests**

```python
from graywind_strategy.backtester import BacktestResult


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
```

Add `from graywind_strategy.backtest_gate import check_fold_thresholds` to the test file's
imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_fold_thresholds'`

- [ ] **Step 3: Implement `check_fold_thresholds`**

Add to `graywind_strategy/backtest_gate.py`:

```python
def check_fold_thresholds(result, fold_index):
    if result.sharpe < FOLD_MIN_SHARPE:
        raise GuardrailViolation(
            f"fold {fold_index}: sharpe {result.sharpe:.3f} below minimum {FOLD_MIN_SHARPE}"
        )
    if result.max_drawdown > FOLD_MAX_DRAWDOWN:
        raise GuardrailViolation(
            f"fold {fold_index}: max drawdown {result.max_drawdown:.1%} exceeds cap "
            f"{FOLD_MAX_DRAWDOWN:.0%}"
        )
    if result.win_rate < FOLD_MIN_WIN_RATE:
        raise GuardrailViolation(
            f"fold {fold_index}: win rate {result.win_rate:.1%} below minimum "
            f"{FOLD_MIN_WIN_RATE:.0%}"
        )
    if len(result.trades) < FOLD_MIN_TRADES:
        raise GuardrailViolation(
            f"fold {fold_index}: only {len(result.trades)} trades, need at least "
            f"{FOLD_MIN_TRADES}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: PASS (11 tests total)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/backtest_gate.py tests/test_backtest_gate.py
git commit -m "feat: add per-fold Sharpe/drawdown/win-rate/trade-count thresholds"
```

---

## Task 5: Deflated Sharpe Ratio math

**Note on the formula:** this is the closed-form Deflated Sharpe Ratio from Bailey & López de
Prado, "The Deflated Sharpe Ratio" (2014). `expected_max_z(n_trials)` is the expected value of
the maximum of `n_trials` draws from a standard normal (an extreme-value-theory
approximation, using the Euler-Mascheroni constant). That z-value gets scaled by the estimated
standard error of the Sharpe estimator (`sr_std`, derived from the sample's own skew/kurtosis
and length) to produce `sr0` — the Sharpe ratio you'd expect to see by pure luck as the best of
`n_trials` candidates. The Probabilistic Sharpe Ratio formula then asks: what's the probability
the true Sharpe exceeds `sr0`, given the observed Sharpe, sample length, skew, and kurtosis?
That probability is the DSR. **Get the scaling of `sr0` right** — an earlier, unscaled version
of this formula (using `sr_std=1.0`) was checked by hand during planning and collapses to ~0.0
for any realistic per-period Sharpe at `n_trials >= 2`, because real per-period Sharpes are
small (roughly `annualized_sharpe / sqrt(periods_per_year)`) while an unscaled `sr0` is order 1.
The formula below divides `sr_std` by `sqrt(n_returns - 1)` specifically to fix that — don't
drop it.

**Files:**
- Modify: `graywind_strategy/backtest_gate.py`
- Test: `tests/test_backtest_gate.py`

**Interfaces:**
- Produces:
  - `_period_returns(equity_curve) -> list[float]`
  - `_skewness(returns) -> float`, `_kurtosis(returns) -> float` (population moments, raw not
    excess kurtosis — a normal distribution scores 3.0, matching the formula's `(kurtosis - 1)`
    term)
  - `expected_max_z(n_trials) -> float` (returns `0.0` for `n_trials < 2`)
  - `probabilistic_sharpe_ratio(sharpe, benchmark_sharpe, n_returns, skew, kurtosis) -> float`
  - `deflated_sharpe_ratio(sharpe, n_trials, n_returns, skew, kurtosis) -> float` — the function
    Task 7's orchestrator calls.

- [ ] **Step 1: Write the failing tests**

```python
from graywind_strategy.backtest_gate import (
    _kurtosis, _period_returns, _skewness, deflated_sharpe_ratio,
    expected_max_z, probabilistic_sharpe_ratio,
)


def test_period_returns_computes_simple_percent_changes():
    assert _period_returns([100.0, 110.0, 99.0]) == pytest.approx([0.10, -0.10])


def test_skewness_of_symmetric_returns_is_zero():
    assert _skewness([0.01, -0.01, 0.02, -0.02, 0.0]) == pytest.approx(0.0, abs=1e-9)


def test_kurtosis_of_symmetric_returns():
    assert _kurtosis([0.01, -0.01, 0.02, -0.02, 0.0]) == pytest.approx(1.7)


def test_skewness_of_left_skewed_returns_is_negative():
    assert _skewness([0.01, 0.01, 0.01, 0.01, -0.10]) == pytest.approx(-1.5)


def test_kurtosis_of_flat_returns_is_normal_default():
    assert _kurtosis([0.0, 0.0, 0.0]) == pytest.approx(3.0)


def test_expected_max_z_is_zero_for_a_single_trial():
    assert expected_max_z(1) == 0.0


def test_expected_max_z_increases_with_more_trials():
    z2 = expected_max_z(2)
    z10 = expected_max_z(10)
    z100 = expected_max_z(100)
    assert z2 == pytest.approx(0.5197553442805939)
    assert z2 < z10 < z100


def test_deflated_sharpe_ratio_decreases_as_trial_count_grows():
    sharpe, n_returns, skew, kurt = 0.06, 500, 0.0, 3.0
    values = [
        deflated_sharpe_ratio(sharpe, nt, n_returns, skew, kurt)
        for nt in (1, 2, 10, 50, 100, 500, 1000)
    ]
    assert values == sorted(values, reverse=True)  # strictly non-increasing in n_trials
    assert values[0] == pytest.approx(0.909729935836157)


def test_deflated_sharpe_ratio_crosses_below_threshold_as_trials_pile_up():
    # Verified by hand during planning: a strategy that clears DSR>=0.95 comfortably
    # as the very first trial can fail it once enough other candidates have been tried.
    sharpe, n_returns, skew, kurt = 0.15, 1000, 0.0, 3.0
    assert deflated_sharpe_ratio(sharpe, 1, n_returns, skew, kurt) == pytest.approx(
        0.9999987890623048
    )
    assert deflated_sharpe_ratio(sharpe, 1000, n_returns, skew, kurt) == pytest.approx(
        0.927783097961449
    )
```

Add the new names to `tests/test_backtest_gate.py`'s import from `graywind_strategy.backtest_gate`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: FAIL — `ImportError` for the not-yet-defined names.

- [ ] **Step 3: Implement the DSR math**

Add to `graywind_strategy/backtest_gate.py`:

```python
def _period_returns(equity_curve):
    return [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]


def _skewness(returns):
    n = len(returns)
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 0.0
    return sum(((r - mean) / stdev) ** 3 for r in returns) / n


def _kurtosis(returns):
    n = len(returns)
    mean = statistics.mean(returns)
    stdev = statistics.pstdev(returns)
    if stdev == 0:
        return 3.0  # neutral (normal-distribution) default for a degenerate zero-variance series
    return sum(((r - mean) / stdev) ** 4 for r in returns) / n


def expected_max_z(n_trials):
    """Expected value of the max of n_trials draws from a standard normal
    (extreme-value-theory approximation, Bailey & Lopez de Prado 2014)."""
    if n_trials < 2:
        return 0.0
    return (
        (1 - _EULER_MASCHERONI) * _STANDARD_NORMAL.inv_cdf(1 - 1.0 / n_trials)
        + _EULER_MASCHERONI * _STANDARD_NORMAL.inv_cdf(1 - 1.0 / (n_trials * math.e))
    )


def probabilistic_sharpe_ratio(sharpe, benchmark_sharpe, n_returns, skew, kurtosis):
    if n_returns < 2:
        return 0.0
    denom = math.sqrt(max(1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2, 1e-12))
    z = (sharpe - benchmark_sharpe) * math.sqrt(n_returns - 1) / denom
    return _STANDARD_NORMAL.cdf(z)


def deflated_sharpe_ratio(sharpe, n_trials, n_returns, skew, kurtosis):
    if n_returns < 2:
        return 0.0
    denom = math.sqrt(max(1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2, 1e-12))
    sr_std = denom / math.sqrt(n_returns - 1)
    sr0 = sr_std * expected_max_z(n_trials)
    return probabilistic_sharpe_ratio(sharpe, sr0, n_returns, skew, kurtosis)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: PASS (20 tests total)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/backtest_gate.py tests/test_backtest_gate.py
git commit -m "feat: add Deflated Sharpe Ratio math for the backtest gate"
```

---

## Task 6: Trial-count log

**Files:**
- Create: `graywind_strategy/backtest_gate_trials.json` (initial content: `[]`)
- Modify: `graywind_strategy/backtest_gate.py`
- Test: `tests/test_backtest_gate.py`

**Interfaces:**
- Produces:
  - `_load_trial_log(path=TRIAL_LOG_PATH) -> list[dict]`
  - `_trial_count(path=TRIAL_LOG_PATH) -> int`
  - `_append_trial(symbol, tier, passed, sharpe, path=TRIAL_LOG_PATH) -> None` — appends one
    row (`symbol`, `tier`, `timestamp` (UTC ISO-8601), `passed`, `sharpe`) and rewrites the file.

- [ ] **Step 1: Create the initial committed log file**

```bash
echo '[]' > graywind_strategy/backtest_gate_trials.json
```

- [ ] **Step 2: Write the failing tests**

```python
import json


def test_trial_count_is_zero_for_a_fresh_log(tmp_path):
    path = tmp_path / "trials.json"
    assert _trial_count(path=path) == 0


def test_append_trial_creates_the_file_if_missing(tmp_path):
    path = tmp_path / "trials.json"
    _append_trial("SERV", tier=3, passed=True, sharpe=0.08, path=path)
    rows = json.loads(path.read_text())
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SERV"
    assert rows[0]["tier"] == 3
    assert rows[0]["passed"] is True
    assert rows[0]["sharpe"] == 0.08
    assert "timestamp" in rows[0]


def test_append_trial_preserves_prior_rows_and_increments_count(tmp_path):
    path = tmp_path / "trials.json"
    _append_trial("AAPL", tier=2, passed=True, sharpe=0.10, path=path)
    _append_trial("SERV", tier=3, passed=False, sharpe=None, path=path)

    rows = json.loads(path.read_text())
    assert [r["symbol"] for r in rows] == ["AAPL", "SERV"]
    assert rows[1]["passed"] is False
    assert rows[1]["sharpe"] is None
    assert _trial_count(path=path) == 2
```

Add `_append_trial`, `_load_trial_log`, `_trial_count` to the test file's import from
`graywind_strategy.backtest_gate`.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: FAIL — `ImportError` for the not-yet-defined names.

- [ ] **Step 4: Implement the trial log functions**

Add to `graywind_strategy/backtest_gate.py`:

```python
def _load_trial_log(path=TRIAL_LOG_PATH):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _trial_count(path=TRIAL_LOG_PATH):
    return len(_load_trial_log(path))


def _append_trial(symbol, tier, passed, sharpe, path=TRIAL_LOG_PATH):
    trials = _load_trial_log(path)
    trials.append({
        "symbol": symbol,
        "tier": tier,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "sharpe": sharpe,
    })
    with open(path, "w") as f:
        json.dump(trials, f, indent=2)
        f.write("\n")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: PASS (23 tests total)

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/backtest_gate.py graywind_strategy/backtest_gate_trials.json tests/test_backtest_gate.py
git commit -m "feat: add persisted trial-count log for the Deflated Sharpe correction"
```

---

## Task 7: Orchestrator — `validate_symbol_backtest`

**Files:**
- Modify: `graywind_strategy/backtest_gate.py`
- Test: `tests/test_backtest_gate.py`

**Interfaces:**
- Consumes: everything from Tasks 2-6 (`fetch_backtest_bars`, `split_into_folds`,
  `check_fold_thresholds`, `_period_returns`/`_skewness`/`_kurtosis`/`deflated_sharpe_ratio`,
  `_trial_count`/`_append_trial`), plus `graywind_strategy.backtester.run_backtest`.
- Produces: `validate_symbol_backtest(symbol, tier, data_client, trial_log_path=TRIAL_LOG_PATH)
  -> None` — the function Task 8 wires into `tier_config.validate_symbol_addition`. Raises
  `GuardrailViolation` on any failure; returns `None` on success. Always appends exactly one
  trial-log row before returning or raising.

**Execution order inside the function** (cheapest/most concrete checks first, subtlest
statistical check last): fetch + history-span floor → one full-period `run_backtest` call →
total-trade-count floor → per-fold `run_backtest` calls + threshold checks (first failing fold
stops the loop) → Deflated Sharpe Ratio check using the full-period result. `n_trials` is read
from the log *before* this candidate is appended (`_trial_count(...) + 1`, counting this
candidate as one of the trials), and the trial is appended *after* every check has run, whether
they passed or the function is about to raise — implemented as `try/except GuardrailViolation:
append(passed=False); raise` / `else: append(passed=True)`.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import patch

from graywind_strategy.backtest_gate import validate_symbol_backtest


def _fake_history_df(n_rows=8):
    return pd.DataFrame({
        "time": pd.date_range("2020-01-01", periods=n_rows, freq="6h"),
        "open": [100.0] * n_rows, "high": [101.0] * n_rows,
        "low": [99.0] * n_rows, "close": [100.0] * n_rows, "volume": [1000] * n_rows,
    })


def _result(**overrides):
    defaults = dict(
        equity_curve=[10000.0] + [10000.0 + i for i in range(1, 400)],
        trades=[{"x": 1}] * 300,
        sharpe=1.5, max_drawdown=0.10, win_rate=0.50, pdt_compliant=True,
    )
    defaults.update(overrides)
    return BacktestResult(**defaults)


def test_validate_symbol_backtest_passes_and_logs_when_every_check_clears(tmp_path):
    log_path = tmp_path / "trials.json"
    full_result = _result()
    fold_result = _result(trades=[{"x": 1}] * 30)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, fold_result, fold_result, fold_result, fold_result]), \
         patch("graywind_strategy.backtest_gate.deflated_sharpe_ratio", return_value=0.99):
        validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SERV"
    assert rows[0]["tier"] == 3
    assert rows[0]["passed"] is True
    assert rows[0]["sharpe"] is not None


def test_validate_symbol_backtest_rejects_and_logs_on_full_period_trade_count_floor(tmp_path):
    log_path = tmp_path / "trials.json"
    thin_result = _result(trades=[{"x": 1}] * 5)  # below MIN_TOTAL_TRADES

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest", return_value=thin_result):
        with pytest.raises(GuardrailViolation, match="total trades"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["passed"] is False
    assert rows[0]["sharpe"] is None  # rejected before a raw sharpe was ever computed


def test_validate_symbol_backtest_rejects_on_a_failing_fold(tmp_path):
    log_path = tmp_path / "trials.json"
    full_result = _result()
    bad_fold = _result(sharpe=0.2)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, bad_fold]):
        with pytest.raises(GuardrailViolation, match="fold 0.*sharpe"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["passed"] is False
    assert rows[0]["sharpe"] is not None  # full-period sharpe was already computed by this point


def test_validate_symbol_backtest_rejects_on_low_deflated_sharpe(tmp_path):
    log_path = tmp_path / "trials.json"
    full_result = _result()
    fold_result = _result(trades=[{"x": 1}] * 30)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, fold_result, fold_result, fold_result, fold_result]), \
         patch("graywind_strategy.backtest_gate.deflated_sharpe_ratio", return_value=0.40):
        with pytest.raises(GuardrailViolation, match="deflated Sharpe"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    rows = json.loads(log_path.read_text())
    assert rows[0]["passed"] is False


def test_validate_symbol_backtest_rejects_before_any_backtest_when_history_too_short(tmp_path):
    log_path = tmp_path / "trials.json"

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars",
               side_effect=GuardrailViolation("SERV has only 90 days of history, "
                                               "backtest gate requires at least 730")), \
         patch("graywind_strategy.backtest_gate.run_backtest") as mock_run_backtest:
        with pytest.raises(GuardrailViolation, match="90 days"):
            validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    mock_run_backtest.assert_not_called()
    rows = json.loads(log_path.read_text())
    assert len(rows) == 1
    assert rows[0]["passed"] is False
    assert rows[0]["sharpe"] is None


def test_validate_symbol_backtest_passes_growing_n_trials_into_deflated_sharpe_ratio(tmp_path):
    log_path = tmp_path / "trials.json"
    log_path.write_text(json.dumps([
        {"symbol": f"SYM{i}", "tier": 2, "timestamp": "2020-01-01T00:00:00+00:00",
         "passed": True, "sharpe": 0.05}
        for i in range(4)
    ]))
    full_result = _result()
    fold_result = _result(trades=[{"x": 1}] * 30)

    with patch("graywind_strategy.backtest_gate.fetch_backtest_bars", return_value=_fake_history_df()), \
         patch("graywind_strategy.backtest_gate.run_backtest",
               side_effect=[full_result, fold_result, fold_result, fold_result, fold_result]), \
         patch("graywind_strategy.backtest_gate.deflated_sharpe_ratio", return_value=0.99) as mock_dsr:
        validate_symbol_backtest("SERV", tier=3, data_client=MagicMock(), trial_log_path=log_path)

    # 4 prior rows + this candidate itself == 5
    assert mock_dsr.call_args.args[1] == 5
```

Add `validate_symbol_backtest` to the test file's import, plus `from
graywind_strategy.guardrails import GuardrailViolation` and `import json` at the top if not
already present from earlier tasks.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_symbol_backtest'`

- [ ] **Step 3: Implement the orchestrator**

Add to `graywind_strategy/backtest_gate.py`:

```python
def validate_symbol_backtest(symbol, tier, data_client, trial_log_path=TRIAL_LOG_PATH):
    n_trials = _trial_count(trial_log_path) + 1
    sharpe_for_log = None
    try:
        df = fetch_backtest_bars(data_client, symbol)

        full_result = run_backtest({symbol: df}, starting_equity=10000.0, gates_always_pass=True)
        if len(full_result.trades) < MIN_TOTAL_TRADES:
            raise GuardrailViolation(
                f"{symbol}: only {len(full_result.trades)} total trades, need at least "
                f"{MIN_TOTAL_TRADES}"
            )

        full_returns = _period_returns(full_result.equity_curve)
        stdev = statistics.pstdev(full_returns) if len(full_returns) >= 2 else 0.0
        raw_sharpe = (statistics.mean(full_returns) / stdev) if stdev else 0.0
        sharpe_for_log = raw_sharpe

        for i, fold_df in enumerate(split_into_folds(df)):
            fold_result = run_backtest(
                {symbol: fold_df}, starting_equity=10000.0, gates_always_pass=True
            )
            check_fold_thresholds(fold_result, i)

        skew = _skewness(full_returns)
        kurtosis = _kurtosis(full_returns)
        dsr = deflated_sharpe_ratio(raw_sharpe, n_trials, len(full_returns), skew, kurtosis)
        if dsr < DSR_THRESHOLD:
            raise GuardrailViolation(
                f"{symbol}: deflated Sharpe ratio {dsr:.3f} below {DSR_THRESHOLD} threshold "
                f"with {n_trials} trials counted"
            )
    except GuardrailViolation:
        _append_trial(symbol, tier, passed=False, sharpe=sharpe_for_log, path=trial_log_path)
        raise
    else:
        _append_trial(symbol, tier, passed=True, sharpe=sharpe_for_log, path=trial_log_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_backtest_gate.py -v`
Expected: PASS (29 tests total)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/backtest_gate.py tests/test_backtest_gate.py
git commit -m "feat: wire fetch, folds, and DSR into validate_symbol_backtest"
```

---

## Task 8: Wire into `validate_symbol_addition`

**Files:**
- Modify: `graywind_strategy/tier_config.py`
- Modify: `tests/test_tier_config.py`

**Interfaces:**
- Consumes: `graywind_strategy.backtest_gate.validate_symbol_backtest(symbol, tier,
  data_client, trial_log_path=...)` (Task 7)
- Produces: `validate_symbol_addition()`'s existing signature and behavior, unchanged except
  for the new final call.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tier_config.py` (needs `from unittest.mock import patch` added to the
existing `from unittest.mock import MagicMock` import line):

```python
def test_validate_symbol_addition_calls_backtest_gate_after_guardrail_checks_pass():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 3_000_000.0}  # clears tier 2
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fake_data_client = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [MagicMock(volume=1_000_000)],
        )
        with patch("graywind_strategy.backtest_gate.validate_symbol_backtest") as mock_gate:
            validate_symbol_addition(
                "AAPL", tier=2, finnhub_api_key="k", data_client=fake_data_client,
                sector="tech", session=fake_session,
            )
    mock_gate.assert_called_once_with("AAPL", 2, fake_data_client)


def test_validate_symbol_addition_propagates_backtest_gate_rejection():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 3_000_000.0}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fake_data_client = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [MagicMock(volume=1_000_000)],
        )
        with patch(
            "graywind_strategy.backtest_gate.validate_symbol_backtest",
            side_effect=GuardrailViolation(
                "SERV: deflated Sharpe ratio 0.400 below 0.95 threshold with 5 trials counted"
            ),
        ):
            with pytest.raises(GuardrailViolation, match="deflated Sharpe"):
                validate_symbol_addition(
                    "SERV", tier=3, finnhub_api_key="k", data_client=fake_data_client,
                    sector="robotics", session=fake_session,
                )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tier_config.py -v`
Expected: FAIL — both new tests fail because `validate_symbol_addition` never calls
`backtest_gate.validate_symbol_backtest` yet (`mock_gate.assert_called_once_with` raises
`AssertionError: Expected ... to have been called once. Called 0 times.`; the rejection test
fails because no exception is raised at all).

- [ ] **Step 3: Wire the call in**

In `graywind_strategy/tier_config.py`, add near the top imports:

```python
from graywind_strategy import backtest_gate
```

Change `validate_symbol_addition`'s body from:

```python
    existing_sector_counts = sector_counts_for_tier(tier, symbol_tier=symbol_tier, sector_map=sector_map)
    check_guardrail(tier, market_cap, avg_volume, sector, existing_sector_counts)
```

to:

```python
    existing_sector_counts = sector_counts_for_tier(tier, symbol_tier=symbol_tier, sector_map=sector_map)
    check_guardrail(tier, market_cap, avg_volume, sector, existing_sector_counts)
    backtest_gate.validate_symbol_backtest(symbol, tier, data_client)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tier_config.py -v`
Expected: PASS, including the two new tests and every pre-existing test in this file
(`test_validate_symbol_addition_raises_on_first_failing_check` still passes because it fails on
market cap before ever reaching the new call).

- [ ] **Step 5: Run the full project test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, all tests green.

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/tier_config.py tests/test_tier_config.py
git commit -m "feat: require the backtest gate to clear before a symbol can be added

validate_symbol_addition() now calls backtest_gate.validate_symbol_backtest()
last, after the existing market-cap/volume/sector checks -- a new tier-2/3
symbol must clear a 4-fold regime-robustness backtest and a Deflated Sharpe
Ratio check before it can be added to SYMBOL_TIER."
```

---

## Deferred, not forgotten

- Sub-project 2 (quarterly performance reports) and sub-project 3 (personal-use advising UI) —
  separate future specs/plans.
- Retroactive backtest-gate validation of the already-live `AAPL`/`SERV` — this gate governs
  future additions only.
- The separate AAPL/SERV backtest sanity-check thread (blocked on the user running
  `scripts/fetch_serv_bars.py` themselves) — unrelated pre-existing work, not touched by this
  plan.
