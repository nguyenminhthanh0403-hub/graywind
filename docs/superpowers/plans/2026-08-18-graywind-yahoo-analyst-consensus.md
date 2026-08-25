# Yahoo Analyst-Consensus Position-Sizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a continuous position-size multiplier, sourced from Yahoo Finance analyst
recommendation trend + price-target consensus, into `decide_trade`.

**Architecture:** A new `graywind_strategy/gates/analyst_consensus.py` holds fetch (`yfinance`),
pure scoring, and CSV-cache read/write functions. A new `evaluate_analyst_consensus_multiplier`
wrapper in `pipeline.py` orchestrates them (cache lookup → fetch-on-miss → fail-open to `1.0`
on error, or immediately on any non-live `as_of_date` to avoid backtest look-ahead bias) and is
applied to `shares` right after the existing sizing call in `decide_trade`.

**Tech Stack:** Python 3.12, `yfinance` (new dependency), `pytest`, `unittest.mock`.

## Global Constraints

- TDD (red/green) for every change to `gates/` or `pipeline.py`, per this project's existing
  convention — write the failing test first for every step below.
- Every gate/source module follows the `fetch_X` (raises `XDataUnavailable`) / pure-logic /
  `evaluate_X` (fail-open or fail-closed wrapper) three-layer split already used by
  `earnings_gate.py`, `macro_gate.py`, `sentiment_gate.py`, `vix_gate.py`.
- `evaluate_analyst_consensus_multiplier` is **fail-open** (`1.0`, no adjustment) on fetch
  failure — a deliberate departure from the other five gates' fail-**closed** contract, per
  spec §Error Handling.
- The multiplier only fetches/applies when `as_of_date == date.today()`; any other date
  (backtest) returns `1.0` immediately, no fetch, no cache read/write — per spec's look-
  ahead-bias guard.
- `gates_always_pass=True` does **not** bypass this multiplier (it isn't a blocking gate).
- Cache file: `state/analyst_consensus.csv`, reusing `state_store.DEFAULT_STATE_DIR` for the
  default directory — do not hardcode `"state"` a second time.
- Spec of record: `docs/superpowers/specs/2026-08-18-graywind-yahoo-analyst-consensus-design.md`.

---

## Task 1: Scoring formula and Yahoo fetch

**Files:**
- Create: `graywind_strategy/gates/analyst_consensus.py`
- Modify: `requirements.txt`
- Test: `tests/test_analyst_consensus.py`

**Interfaces:**
- Produces: `AnalystDataUnavailable(Exception)`; `fetch_analyst_consensus(symbol,
  ticker_factory=yfinance.Ticker) -> tuple[float, float]` (returns
  `(recommendation_mean, target_mean)`, raises `AnalystDataUnavailable` on any fetch error or
  missing/`None` field); `analyst_consensus_multiplier(recommendation_mean, target_mean,
  current_price) -> float` (pure, no I/O).

- [ ] **Step 1: Add `yfinance` to `requirements.txt`**

Add a new line `yfinance` to `requirements.txt` (alphabetical position doesn't matter — the
existing file isn't sorted). Then install it:

Run: `pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests for `analyst_consensus_multiplier`**

```python
# tests/test_analyst_consensus.py
from graywind_strategy.gates.analyst_consensus import analyst_consensus_multiplier


def test_multiplier_strong_buy_at_current_price_target():
    # recommendation_mean=1.0 (Strong Buy), target_mean == current_price (0% upside)
    result = analyst_consensus_multiplier(
        recommendation_mean=1.0, target_mean=100.0, current_price=100.0
    )
    assert result == 1.075  # (1.15 + 1.00) / 2


def test_multiplier_strong_sell_at_current_price_target():
    result = analyst_consensus_multiplier(
        recommendation_mean=5.0, target_mean=100.0, current_price=100.0
    )
    assert result == 0.925  # (0.85 + 1.00) / 2


def test_multiplier_hold_with_zero_upside_is_exactly_neutral():
    result = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=100.0, current_price=100.0
    )
    assert result == 1.0


def test_multiplier_clamps_upside_beyond_15_percent():
    # target_mean is 30% above current_price -- clamps to the same result as exactly +15%
    result_30pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=130.0, current_price=100.0
    )
    result_15pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=115.0, current_price=100.0
    )
    assert result_30pct == result_15pct == 1.075  # (1.00 + 1.15) / 2


def test_multiplier_clamps_downside_beyond_15_percent():
    result_30pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=70.0, current_price=100.0
    )
    result_15pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=85.0, current_price=100.0
    )
    assert result_30pct == result_15pct == 0.925  # (1.00 + 0.85) / 2


def test_multiplier_clamps_recommendation_mean_outside_1_to_5():
    # a recommendation_mean of 7 (outside Yahoo's documented 1-5 scale) clamps to 5 (Strong Sell)
    result_out_of_range = analyst_consensus_multiplier(
        recommendation_mean=7.0, target_mean=100.0, current_price=100.0
    )
    result_at_bound = analyst_consensus_multiplier(
        recommendation_mean=5.0, target_mean=100.0, current_price=100.0
    )
    assert result_out_of_range == result_at_bound == 0.925
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_analyst_consensus.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.gates.analyst_consensus'`

- [ ] **Step 4: Implement the scoring function**

```python
# graywind_strategy/gates/analyst_consensus.py
"""Yahoo analyst-consensus position-size multiplier: scales a trade's share
count up or down based on analyst recommendation trend and price-target
consensus. Unlike the five boolean gates in this package, this never blocks
a trade -- it fails open (multiplier of 1.0, no adjustment) on any fetch
failure, and returns 1.0 unconditionally for any non-live as_of_date, since
yfinance has no historical point-in-time query and decide_trade is the
single path both live_loop.py and backtester.py call (see pipeline.py's
evaluate_analyst_consensus_multiplier for that guard).
"""
import csv
import os

import yfinance as yf

from graywind_strategy.state_store import DEFAULT_STATE_DIR

CACHE_FILENAME = "analyst_consensus.csv"
CACHE_FIELDS = ["symbol", "date", "recommendation_mean", "target_mean", "multiplier"]

REC_MIN, REC_MAX = 1.0, 5.0
MULTIPLIER_MIN, MULTIPLIER_MAX = 0.85, 1.15
TARGET_UPSIDE_CLAMP = 0.15


class AnalystDataUnavailable(Exception):
    pass


def _clamp(value, low, high):
    return max(low, min(high, value))


def analyst_consensus_multiplier(recommendation_mean, target_mean, current_price):
    rec_clamped = _clamp(recommendation_mean, REC_MIN, REC_MAX)
    # Strong Buy (REC_MIN) maps to MULTIPLIER_MAX, Strong Sell (REC_MAX) maps to MULTIPLIER_MIN.
    rec_fraction = (rec_clamped - REC_MIN) / (REC_MAX - REC_MIN)
    multiplier_rec = MULTIPLIER_MAX - rec_fraction * (MULTIPLIER_MAX - MULTIPLIER_MIN)

    pct_upside = (target_mean - current_price) / current_price
    multiplier_target = 1.0 + _clamp(pct_upside, -TARGET_UPSIDE_CLAMP, TARGET_UPSIDE_CLAMP)

    return (multiplier_rec + multiplier_target) / 2
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_analyst_consensus.py -v`
Expected: 6 PASS

- [ ] **Step 6: Write the failing tests for `fetch_analyst_consensus`**

```python
# append to tests/test_analyst_consensus.py
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.analyst_consensus import (
    AnalystDataUnavailable,
    fetch_analyst_consensus,
)


def test_fetch_analyst_consensus_returns_recommendation_and_target():
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": 2.1, "targetMeanPrice": 210.5}
    fake_ticker_factory = MagicMock(return_value=fake_ticker)

    result = fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)

    assert result == (2.1, 210.5)
    fake_ticker_factory.assert_called_once_with("AAPL")


def test_fetch_analyst_consensus_raises_on_ticker_exception():
    fake_ticker_factory = MagicMock(side_effect=Exception("network error"))
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_on_missing_recommendation_mean():
    fake_ticker = MagicMock()
    fake_ticker.info = {"targetMeanPrice": 210.5}  # recommendationMean absent
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_on_missing_target_mean_price():
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": 2.1}  # targetMeanPrice absent
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_analyst_consensus.py -v`
Expected: the 4 new tests FAIL with `ImportError: cannot import name 'fetch_analyst_consensus'`

- [ ] **Step 8: Implement `fetch_analyst_consensus`**

Add to `graywind_strategy/gates/analyst_consensus.py` (below the imports, above
`analyst_consensus_multiplier` or after it — position doesn't matter):

```python
def fetch_analyst_consensus(symbol, ticker_factory=yf.Ticker):
    try:
        info = ticker_factory(symbol).info
        recommendation_mean = info.get("recommendationMean")
        target_mean = info.get("targetMeanPrice")
    except Exception as exc:
        raise AnalystDataUnavailable(str(exc)) from exc
    if recommendation_mean is None or target_mean is None:
        raise AnalystDataUnavailable(f"missing analyst consensus fields for {symbol}")
    return float(recommendation_mean), float(target_mean)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_analyst_consensus.py -v`
Expected: 10 PASS

- [ ] **Step 10: Commit**

```bash
git add requirements.txt graywind_strategy/gates/analyst_consensus.py tests/test_analyst_consensus.py
git commit -m "feat: add analyst-consensus scoring and Yahoo fetch"
```

---

## Task 2: Persisted daily cache

**Files:**
- Modify: `graywind_strategy/gates/analyst_consensus.py`
- Test: `tests/test_analyst_consensus.py`

**Interfaces:**
- Consumes: `CACHE_FILENAME`, `CACHE_FIELDS` (module constants from Task 1).
- Produces: `load_cached_multiplier(symbol, as_of_date, state_dir=DEFAULT_STATE_DIR) ->
  float | None`; `save_cached_multiplier(symbol, as_of_date, recommendation_mean, target_mean,
  multiplier, state_dir=DEFAULT_STATE_DIR) -> None`.

- [ ] **Step 1: Write the failing cache tests**

```python
# append to tests/test_analyst_consensus.py
from datetime import date

from graywind_strategy.gates.analyst_consensus import (
    load_cached_multiplier,
    save_cached_multiplier,
)


def test_load_cached_multiplier_returns_none_when_file_does_not_exist(tmp_path):
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_save_then_load_round_trips_the_multiplier(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result == 1.075


def test_load_cached_multiplier_misses_on_a_different_date(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    result = load_cached_multiplier("AAPL", date(2026, 8, 19), state_dir=str(tmp_path))
    assert result is None


def test_load_cached_multiplier_misses_on_a_different_symbol(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    result = load_cached_multiplier("MSFT", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_save_appends_rather_than_overwrites_other_symbols(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    save_cached_multiplier(
        "MSFT", date(2026, 8, 18),
        recommendation_mean=1.8, target_mean=420.0, multiplier=1.1,
        state_dir=str(tmp_path),
    )
    assert load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path)) == 1.075
    assert load_cached_multiplier("MSFT", date(2026, 8, 18), state_dir=str(tmp_path)) == 1.1


def test_load_cached_multiplier_treats_malformed_row_as_a_miss(tmp_path):
    os_makedirs_path = tmp_path / "analyst_consensus.csv"
    os_makedirs_path.write_text(
        "symbol,date,recommendation_mean,target_mean,multiplier\n"
        "AAPL,2026-08-18,2.1,210.5,not-a-number\n"
    )
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_load_cached_multiplier_treats_corrupt_file_as_a_miss(tmp_path):
    (tmp_path / "analyst_consensus.csv").write_bytes(b"\xff\xfe\x00\x01not,csv,at,all")
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_analyst_consensus.py -v`
Expected: the 7 new tests FAIL with `ImportError: cannot import name 'load_cached_multiplier'`

- [ ] **Step 3: Implement the cache functions**

Add to `graywind_strategy/gates/analyst_consensus.py`:

```python
def load_cached_multiplier(symbol, as_of_date, state_dir=DEFAULT_STATE_DIR):
    path = os.path.join(state_dir, CACHE_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("symbol") == symbol and row.get("date") == as_of_date.isoformat():
                    return float(row["multiplier"])
    except Exception:
        return None
    return None


def save_cached_multiplier(symbol, as_of_date, recommendation_mean, target_mean, multiplier,
                            state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, CACHE_FILENAME)
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CACHE_FIELDS, lineterminator="\n")
        if write_header:
            writer.writeheader()
        writer.writerow({
            "symbol": symbol,
            "date": as_of_date.isoformat(),
            "recommendation_mean": recommendation_mean,
            "target_mean": target_mean,
            "multiplier": multiplier,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_analyst_consensus.py -v`
Expected: 17 PASS

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/analyst_consensus.py tests/test_analyst_consensus.py
git commit -m "feat: add persisted daily cache for analyst-consensus multiplier"
```

---

## Task 3: `evaluate_analyst_consensus_multiplier` wrapper in `pipeline.py`

**Files:**
- Modify: `graywind_strategy/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `AnalystDataUnavailable`, `fetch_analyst_consensus`, `analyst_consensus_multiplier`,
  `load_cached_multiplier`, `save_cached_multiplier` (all from Tasks 1-2).
- Produces: `evaluate_analyst_consensus_multiplier(symbol, as_of_date, current_price) -> float`
  — importable from `graywind_strategy.pipeline`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_pipeline.py (add these imports to the existing import block at top)
from datetime import date
from graywind_strategy.gates.analyst_consensus import AnalystDataUnavailable
from graywind_strategy.pipeline import evaluate_analyst_consensus_multiplier


def test_evaluate_analyst_consensus_multiplier_returns_neutral_for_non_today_date():
    # Task 11/backtest dates are never date.today() in a real run; this proves the
    # look-ahead-bias guard without needing to mock fetch or cache at all.
    with patch("graywind_strategy.pipeline.fetch_analyst_consensus") as mock_fetch:
        result = evaluate_analyst_consensus_multiplier(
            symbol="AAPL", as_of_date=date(2024, 1, 8), current_price=100.0
        )
    assert result == 1.0
    mock_fetch.assert_not_called()


def test_evaluate_analyst_consensus_multiplier_fails_open_on_fetch_error():
    with patch("graywind_strategy.pipeline.load_cached_multiplier", return_value=None), \
         patch("graywind_strategy.pipeline.fetch_analyst_consensus",
               side_effect=AnalystDataUnavailable("boom")):
        result = evaluate_analyst_consensus_multiplier(
            symbol="AAPL", as_of_date=date.today(), current_price=100.0
        )
    assert result == 1.0


def test_evaluate_analyst_consensus_multiplier_uses_cache_hit_without_fetching():
    with patch("graywind_strategy.pipeline.load_cached_multiplier", return_value=1.075), \
         patch("graywind_strategy.pipeline.fetch_analyst_consensus") as mock_fetch:
        result = evaluate_analyst_consensus_multiplier(
            symbol="AAPL", as_of_date=date.today(), current_price=100.0
        )
    assert result == 1.075
    mock_fetch.assert_not_called()


def test_evaluate_analyst_consensus_multiplier_fetches_scores_and_caches_on_a_miss():
    with patch("graywind_strategy.pipeline.load_cached_multiplier", return_value=None), \
         patch("graywind_strategy.pipeline.fetch_analyst_consensus",
               return_value=(1.0, 100.0)) as mock_fetch, \
         patch("graywind_strategy.pipeline.save_cached_multiplier") as mock_save:
        result = evaluate_analyst_consensus_multiplier(
            symbol="AAPL", as_of_date=date.today(), current_price=100.0
        )
    assert result == 1.075  # Strong Buy, 0% upside
    mock_fetch.assert_called_once_with("AAPL")
    mock_save.assert_called_once_with(
        "AAPL", date.today(), recommendation_mean=1.0, target_mean=100.0, multiplier=1.075,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: the 4 new tests FAIL with `ImportError: cannot import name
'evaluate_analyst_consensus_multiplier'`

- [ ] **Step 3: Implement the wrapper**

Add to `graywind_strategy/pipeline.py`: first add `from datetime import date` to the existing
`from typing import Optional` import line's neighborhood (top of file), then add the new gate
import block below the existing `sentiment_gate` import block, then add the wrapper function
below the existing `evaluate_macro_gate` function (around line 68 in the current file):

```python
from datetime import date
```
(add alongside the existing `from dataclasses import dataclass` line at the top of the file)

```python
from graywind_strategy.gates.analyst_consensus import (
    AnalystDataUnavailable,
    analyst_consensus_multiplier,
    fetch_analyst_consensus,
    load_cached_multiplier,
    save_cached_multiplier,
)
```
(add below the existing `from graywind_strategy.gates.macro_gate import ...` import line)

```python
def evaluate_analyst_consensus_multiplier(symbol, as_of_date, current_price):
    if as_of_date != date.today():
        # yfinance has no historical point-in-time query -- applying it to a
        # backtest as_of_date would leak today's analyst opinions into a
        # historical decision. Neutral is the honest answer for any date
        # that isn't live "today".
        return 1.0

    cached = load_cached_multiplier(symbol, as_of_date)
    if cached is not None:
        return cached

    try:
        recommendation_mean, target_mean = fetch_analyst_consensus(symbol)
    except AnalystDataUnavailable:
        return 1.0

    multiplier = analyst_consensus_multiplier(recommendation_mean, target_mean, current_price)
    save_cached_multiplier(
        symbol, as_of_date,
        recommendation_mean=recommendation_mean, target_mean=target_mean, multiplier=multiplier,
    )
    return multiplier
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: the 4 new tests PASS, all pre-existing tests still PASS

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/pipeline.py tests/test_pipeline.py
git commit -m "feat: add evaluate_analyst_consensus_multiplier wrapper to pipeline"
```

---

## Task 4: Wire the multiplier into `decide_trade`

**Files:**
- Modify: `graywind_strategy/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `evaluate_analyst_consensus_multiplier` (Task 3).
- Produces: no new public interface — this task changes `decide_trade`'s internal share-count
  computation only. `decide_trade`'s own signature is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_pipeline.py
def test_decide_trade_applies_analyst_consensus_multiplier_to_shares_on_a_live_date():
    with _passing_gates(), \
         patch("graywind_strategy.pipeline.evaluate_analyst_consensus_multiplier",
               return_value=1.2) as mock_multiplier:
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date.today(),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    base_shares = PositionSizer(risk_fraction=0.01).shares_to_buy(10000.0, 100.0, 98.0)
    assert decision.action == "buy"
    assert decision.shares == round(base_shares * 1.2)
    mock_multiplier.assert_called_once_with(
        symbol="AAPL", as_of_date=date.today(), current_price=100.0
    )


def test_decide_trade_applies_multiplier_even_when_gates_always_pass():
    with patch("graywind_strategy.pipeline.evaluate_analyst_consensus_multiplier",
               return_value=0.9) as mock_multiplier:
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date.today(),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
            gates_always_pass=True,
        )
    base_shares = PositionSizer(risk_fraction=0.01).shares_to_buy(10000.0, 100.0, 98.0)
    assert decision.action == "buy"
    assert decision.shares == round(base_shares * 0.9)
    mock_multiplier.assert_called_once()
```

Also add `date.today()` handling awareness to the existing pinned-math test
(`test_decide_trade_buys_when_signal_and_all_gates_and_risk_checks_pass`, currently asserting
`decision.shares == ... == 50`): **no change needed there** — it uses `as_of_date=date(2024, 1,
8)`, which is never `date.today()`, so `evaluate_analyst_consensus_multiplier` returns `1.0`
via the look-ahead-bias guard automatically and that test's existing exact-`50` assertion
keeps passing unmodified. Confirm this in Step 4 by watching it stay green, not by editing it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: the 2 new tests FAIL — `decision.shares` won't match `round(base_shares * 1.2)` /
`round(base_shares * 0.9)` because the multiplier isn't wired in yet (shares will equal
`base_shares` exactly).

- [ ] **Step 3: Wire the multiplier into `decide_trade`**

In `graywind_strategy/pipeline.py`, modify `decide_trade`'s existing sizing block:

```python
    target_price = position_sizer.take_profit_price(current_price, take_profit_pct)
    shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
    shares = round(shares * evaluate_analyst_consensus_multiplier(
        symbol=symbol, as_of_date=as_of_date, current_price=current_price))
    if shares <= 0:
        return TradeDecision(action="hold", reason="position size rounds to zero shares")
```

Only the new `shares = round(...)` line is inserted, between the existing `shares =
position_sizer.shares_to_buy(...)` line and the existing `if shares <= 0:` check. The
`target_price = ...` line above and the `if shares <= 0:` check below are unchanged — shown
here only for placement context.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: ALL tests PASS, including the 2 new ones and the pre-existing pinned-math test
(`test_decide_trade_buys_when_signal_and_all_gates_and_risk_checks_pass`) unchanged.

- [ ] **Step 5: Run the full test suite**

Run: `python3 -m pytest tests/ -q`
Expected: ALL tests PASS (197+ passing, up from the pre-feature 196).

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/pipeline.py tests/test_pipeline.py
git commit -m "feat: apply analyst-consensus multiplier to decide_trade's share sizing"
```

---

## Task 5: Confirm backtester coverage and close out the spec's testing section

**Files:**
- Read only: `tests/test_backtester.py`, `graywind_strategy/backtester.py`

**Interfaces:**
- Consumes: nothing new — this task verifies existing behavior, no code changes expected.

This task exists because the spec (`docs/superpowers/specs/2026-08-18-graywind-yahoo-analyst-
consensus-design.md`, §Testing) calls for "one new case in `test_backtester.py` confirming a
historical backtest run gets neutral multipliers throughout." Investigating during planning
found that **every existing test in `test_backtester.py` mocks `decide_trade` out entirely**
(`patch("graywind_strategy.backtester.decide_trade", side_effect=fake_decide_trade)`) — none of
them exercise real `decide_trade` internals. Adding a "real" end-to-end test there would break
from that file's own convention and require a decide_trade call that isn't mocked, which no
other test in the file does.

The actual guarantee the spec wants is already fully covered by two things that exist after
Tasks 3-4, without adding a mismatched test:
1. `test_evaluate_analyst_consensus_multiplier_returns_neutral_for_non_today_date` (Task 3) —
   unit-proves the guard itself.
2. `run_backtest`'s existing tests already assert `decide_trade` is called with
   `as_of_date=current_day` (the historical bar's own date, never `date.today()` in a real
   backtest) — proving the guard's precondition is always met in practice.

- [ ] **Step 1: Confirm the finding**

Run: `grep -n "patch(\"graywind_strategy.backtester.decide_trade\"" tests/test_backtester.py`
Expected: every `decide_trade`-related test in the file uses this mock pattern — confirms no
existing test calls the real `decide_trade`.

- [ ] **Step 2: Confirm `as_of_date` is always the historical bar's date, never `date.today()`**

Run: `grep -n "as_of_date=current_day" graywind_strategy/backtester.py`
Expected: one match, inside `run_backtest`'s call to `decide_trade` — confirms `as_of_date` is
always derived from the historical bar being replayed, structurally never `date.today()`
during a real backtest run over historical data.

- [ ] **Step 3: No commit for this task**

No files change. If either grep in Steps 1-2 doesn't match as expected, stop and re-open Task 5
as a real code task instead of closing it out here — do not silently skip a failed check.

---

## Post-plan: update the spec's testing note (optional, small)

Not a numbered task since it's pure documentation and touches only the already-committed spec,
but worth doing for a future reader: add a one-line note to the spec's §Testing section
recording that the `test_backtester.py` case was deliberately not added, and why (Task 5's
finding). If skipped, no functional impact — just a minor spec/implementation drift for a
future reader to notice via this plan instead.
