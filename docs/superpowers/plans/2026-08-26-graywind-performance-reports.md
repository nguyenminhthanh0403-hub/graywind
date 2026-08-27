# Graywind Quarterly Performance Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user quarterly profit/loss reporting with a real "why" — per-gate values captured going forward, a manually-triggered report script, and a new dashboard section — for both the $100k and $2k paper accounts.

**Architecture:** A new `GateResult` dataclass (own leaf module, to avoid a circular import with `gates/sector_gates.py`) lets each of the five signal-augmentation gates carry its underlying value home from `decide_trade` without changing any existing boolean control flow. `live_loop.py` appends one `decision_log.csv` row per `decide_trade` call, every cycle, to each account's own `GRAYWIND_STATE_DIR`. A new one-off script reads `decision_log.csv` + the existing `trade_log.csv`/`equity_curve.csv`, computes metrics with the backtester's already-tested pure functions, builds a why-narrative, and writes `performance_report.json` per account. A new `workflow_dispatch`-only GitHub Actions workflow runs it. `index.html` gets a new section rendering the JSON.

**Tech Stack:** Python 3.14 (project `.venv`), pandas/dataclasses/csv/json stdlib, pytest, vanilla JS + D3 (already loaded) for the dashboard, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-26-graywind-performance-reports-design.md`

## Global Constraints

- Report generation is manually triggerable via `workflow_dispatch` only — never wired onto the existing 15-minute `live-trading.yml` cron.
- No retroactive "why" reconstruction for the 6 pre-existing trades — they keep their generic `reason`, shown honestly as limited-context.
- Both accounts ($100k default, $2k `state/small`/`dashboard-data/small`) are computed and reported side by side; the small account is skipped gracefully (not an error) if its dashboard files don't exist yet.
- Report output is published to the public dashboard (`dashboard-data/performance_report.json` and its `small/` counterpart), not a private file — the user's own explicit choice.
- `GateResult.__bool__` returning `.passed` is load-bearing: every existing `if not evaluate_x_gate(...)` line in `decide_trade` must need zero control-flow changes.
- `decision_log.csv` write failures must raise, never silently skip (same fail-loud principle as every other guardrail/log in this project).
- `generate-performance-report.yml`'s failure must not affect the existing `live-trading.yml` cron — separate workflow, no shared job dependency.
- Full test suite baseline is **322/322 passing** as of `e2197be`. Run `.venv/bin/python -m pytest tests/ -q` after every task and keep it green throughout.

---

## Task 1: `GateResult` dataclass

**Files:**
- Create: `graywind_strategy/gate_result.py`
- Test: `tests/test_gate_result.py`

**Interfaces:**
- Produces: `GateResult(passed: bool, value: object = None, detail: str = "")` with `__bool__` returning `.passed`. Every later task imports this from `graywind_strategy.gate_result`.

**Deviation from the spec's literal wording, noted here so it isn't re-litigated:** the spec says `GateResult` lives "in `graywind_strategy/pipeline.py`". It must not: `pipeline.py` imports `evaluate_sector_gates` FROM `graywind_strategy/gates/sector_gates.py` (Task 3 needs `GateResult` there too), so putting the dataclass in `pipeline.py` would make `sector_gates.py` import back from `pipeline.py` — a circular import. `graywind_strategy/gate_result.py` is a leaf module (no project imports) both sides can import from with no cycle. `pipeline.py` still imports and re-exposes the name (`from graywind_strategy.gate_result import GateResult`), so `graywind_strategy.pipeline.GateResult` also resolves correctly for anyone who expected it there.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gate_result.py
from graywind_strategy.gate_result import GateResult


def test_gate_result_is_truthy_when_passed():
    result = GateResult(passed=True, value=15.0)
    assert bool(result) is True
    assert result if result else False  # exercises __bool__ in an `if` context


def test_gate_result_is_falsy_when_not_passed():
    result = GateResult(passed=False, detail="VixDataUnavailable")
    assert bool(result) is False
    assert not result


def test_gate_result_defaults_value_and_detail():
    result = GateResult(passed=True)
    assert result.value is None
    assert result.detail == ""


def test_gate_result_works_in_existing_if_not_idiom():
    # Pins the exact idiom decide_trade uses today: `if not evaluate_x_gate(...)`.
    passing = GateResult(passed=True, value=1)
    blocking = GateResult(passed=False)
    assert not (not passing)
    assert not blocking
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_gate_result.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.gate_result'`

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/gate_result.py
"""Shared result type for the five signal-augmentation gates
(vix/sentiment/earnings/macro/sector) evaluated in pipeline.py and
gates/sector_gates.py. Lives in its own leaf module (no project imports)
so both of those modules can import it without a circular import --
pipeline.py already imports evaluate_sector_gates FROM
gates/sector_gates.py, so a GateResult defined inside pipeline.py would
force gates/sector_gates.py to import back from pipeline.py.
"""
from dataclasses import dataclass


@dataclass
class GateResult:
    passed: bool
    value: object = None
    detail: str = ""

    def __bool__(self):
        return self.passed
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_gate_result.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gate_result.py tests/test_gate_result.py
git commit -m "feat: add GateResult, a bool-compatible pass/value/detail carrier for gate wrappers"
```

---

## Task 2: Wire `GateResult` into `pipeline.py`'s four gate wrappers

**Files:**
- Modify: `graywind_strategy/pipeline.py` (the `evaluate_vix_gate`/`evaluate_sentiment_gate`/`evaluate_earnings_gate`/`evaluate_macro_gate` functions)
- Modify: `graywind_strategy/gates/macro_gate.py` (extract a `count_macro_breaches` helper so `evaluate_macro_gate` can get the breach count without duplicating `macro_gate`'s vote logic)
- Modify: `tests/test_pipeline.py` (rewrite the wrapper-level tests that currently do identity checks like `is True`/`is False` against a bare bool — those break once the return type is `GateResult`, per the spec's own note that these tests need updating)
- Modify: `tests/test_macro_gate.py` (add a test for the new helper)

**Interfaces:**
- Consumes: `GateResult` from `graywind_strategy.gate_result` (Task 1).
- Produces: `evaluate_vix_gate`, `evaluate_sentiment_gate`, `evaluate_earnings_gate`, `evaluate_macro_gate` each now return a `GateResult` instead of `bool`. `count_macro_breaches(snapshot) -> int` in `graywind_strategy/gates/macro_gate.py`, used by both `macro_gate()` (unchanged return type — still a bare `bool`, its own tests still assert `is True`/`is False`) and `evaluate_macro_gate`.

**Why `macro_gate()` itself is untouched:** `tests/test_macro_gate.py` asserts `macro_gate(snapshot) is True` (identity, not truthiness) directly against the pure function — that's a real, intentional invariant of a pure boolean function, not an oversight to "fix" by widening its return type. Only `evaluate_macro_gate` (the wrapper `decide_trade` actually calls) needs the value; extracting the vote-counting into `count_macro_breaches` lets both `macro_gate()` and `evaluate_macro_gate` reuse the same logic without either duplicating it or changing `macro_gate`'s public contract.

- [ ] **Step 1: Write the failing tests**

Replace the seven identity-assertion wrapper tests in `tests/test_pipeline.py` (`test_evaluate_vix_gate_fails_closed_on_fetch_error`, `test_evaluate_vix_gate_passes_through_on_success`, `test_evaluate_sentiment_gate_fails_closed_on_fetch_error`, `test_evaluate_sentiment_gate_forwards_as_of_date_to_fetch`, `test_evaluate_earnings_gate_fails_closed_on_fetch_error`, `test_evaluate_macro_gate_fails_closed_on_fetch_error`, `test_evaluate_macro_gate_passes_through_on_success`) with the versions below, and add the new `.value`-focused tests. Also add `from graywind_strategy.gate_result import GateResult` to the file's imports.

```python
# tests/test_pipeline.py -- add to imports at top of file
from graywind_strategy.gate_result import GateResult
```

```python
# tests/test_pipeline.py -- replace the seven named tests above with:

def test_evaluate_vix_gate_fails_closed_on_fetch_error():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", side_effect=VixDataUnavailable("boom")):
        result = evaluate_vix_gate(fred_api_key="k", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert bool(result) is False
    assert result.detail == "VixDataUnavailable"


def test_evaluate_vix_gate_passes_through_on_success():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", return_value=15.0) as mock_fetch:
        result = evaluate_vix_gate(fred_api_key="k", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert bool(result) is True
    assert result.value == 15.0
    mock_fetch.assert_called_once_with("k", today=date(2024, 1, 8))


def test_evaluate_sentiment_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_recent_headlines",
        side_effect=SentimentDataUnavailable("boom"),
    ):
        result = evaluate_sentiment_gate(news_client=object(), symbol="AAPL", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.detail == "SentimentDataUnavailable"


def test_evaluate_sentiment_gate_forwards_as_of_date_to_fetch():
    news_client = object()
    with patch("graywind_strategy.pipeline.fetch_recent_headlines", return_value=[]) as mock_fetch:
        result = evaluate_sentiment_gate(news_client=news_client, symbol="AAPL", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == 0.0  # sentiment_score([]) == 0.0 (neutral, no headlines)
    mock_fetch.assert_called_once_with(news_client, "AAPL", as_of=date(2024, 1, 8))


def test_evaluate_earnings_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_next_earnings_date",
        side_effect=EarningsDataUnavailable("boom"),
    ):
        result = evaluate_earnings_gate(symbol="AAPL", finnhub_api_key="k", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.detail == "EarningsDataUnavailable"


def test_evaluate_earnings_gate_value_is_none_when_no_earnings_scheduled():
    with patch("graywind_strategy.pipeline.fetch_next_earnings_date", return_value=None):
        result = evaluate_earnings_gate(symbol="AAPL", finnhub_api_key="k", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value is None


def test_evaluate_earnings_gate_value_is_days_until_next_earnings():
    with patch("graywind_strategy.pipeline.fetch_next_earnings_date", return_value=date(2024, 1, 20)):
        result = evaluate_earnings_gate(symbol="AAPL", finnhub_api_key="k", as_of_date=date(2024, 1, 8))
    assert result.passed is True  # 12 days > EARNINGS_BLACKOUT_DAYS (3)
    assert result.value == 12


def test_evaluate_macro_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_bullion_macro_snapshot",
        side_effect=MacroDataUnavailable("boom"),
    ):
        result = evaluate_macro_gate(as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.detail == "MacroDataUnavailable"


def test_evaluate_macro_gate_passes_through_on_success():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    with patch(
        "graywind_strategy.pipeline.fetch_bullion_macro_snapshot", return_value=snapshot
    ) as mock_fetch:
        result = evaluate_macro_gate(as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == 0  # zero breaches
    mock_fetch.assert_called_once_with(date(2024, 1, 8), session=requests)


def test_evaluate_macro_gate_value_is_breach_count_when_gate_fails():
    snapshot = {"vix": 14.6, "nfci": 0.1, "hy_oas": 6.0, "curve_slope": 0.48}  # nfci + hy_oas both breach
    with patch("graywind_strategy.pipeline.fetch_bullion_macro_snapshot", return_value=snapshot):
        result = evaluate_macro_gate(as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.value == 2
```

Add one new test to `tests/test_macro_gate.py`:

```python
# tests/test_macro_gate.py -- add to imports
from graywind_strategy.gates.macro_gate import count_macro_breaches  # alongside the existing imports


def test_count_macro_breaches_counts_each_breaching_field():
    snapshot = {"vix": 999.0, "nfci": 0.1, "hy_oas": 6.0, "curve_slope": -0.1}
    assert count_macro_breaches(snapshot) == 3  # nfci, hy_oas, curve_slope all breach; vix excluded from the vote


def test_count_macro_breaches_is_zero_when_nothing_breaches():
    snapshot = {"vix": 14.6, "nfci": -0.55, "hy_oas": 2.71, "curve_slope": 0.48}
    assert count_macro_breaches(snapshot) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_macro_gate.py -v`
Expected: FAIL — the rewritten `test_pipeline.py` tests fail because the wrappers still return `bool` (`.passed` raises `AttributeError` on a plain `True`/`False`); `test_count_macro_breaches_*` fail with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/gates/macro_gate.py -- replace the existing macro_gate function with:

def count_macro_breaches(snapshot):
    breaches = 0
    if snapshot["nfci"] >= NFCI_THRESHOLD:
        breaches += 1
    if snapshot["hy_oas"] >= HY_OAS_THRESHOLD:
        breaches += 1
    if snapshot["curve_slope"] < CURVE_SLOPE_THRESHOLD:
        breaches += 1
    return breaches


def macro_gate(snapshot, required_breaches=2):
    return count_macro_breaches(snapshot) < required_breaches
```

```python
# graywind_strategy/pipeline.py -- add to imports
from graywind_strategy.gate_result import GateResult
from graywind_strategy.gates.macro_gate import (
    MacroDataUnavailable, count_macro_breaches, fetch_bullion_macro_snapshot,
)
# (replaces the existing `from graywind_strategy.gates.macro_gate import
# MacroDataUnavailable, fetch_bullion_macro_snapshot, macro_gate` line -- `macro_gate`
# itself drops out of this import entirely: evaluate_macro_gate now calls
# count_macro_breaches directly instead of the bare macro_gate() bool function,
# so keeping the old name imported here would be dead/unused)
```

```python
# graywind_strategy/pipeline.py -- replace the four evaluate_*_gate functions with:

def evaluate_vix_gate(fred_api_key, as_of_date=None, threshold=VIX_THRESHOLD):
    try:
        vix_value = fetch_latest_vix(fred_api_key, today=as_of_date)
    except VixDataUnavailable:
        return GateResult(passed=False, detail="VixDataUnavailable")
    return GateResult(passed=vix_gate(vix_value, threshold), value=vix_value)


def evaluate_sentiment_gate(news_client, symbol, as_of_date=None, threshold=SENTIMENT_THRESHOLD):
    try:
        headlines = fetch_recent_headlines(news_client, symbol, as_of=as_of_date)
    except SentimentDataUnavailable:
        return GateResult(passed=False, detail="SentimentDataUnavailable")
    score = sentiment_score(headlines)
    return GateResult(passed=sentiment_gate(score, threshold), value=score)


def evaluate_earnings_gate(symbol, finnhub_api_key, as_of_date, blackout_days=EARNINGS_BLACKOUT_DAYS):
    try:
        next_date = fetch_next_earnings_date(symbol, finnhub_api_key, as_of_date)
    except EarningsDataUnavailable:
        return GateResult(passed=False, detail="EarningsDataUnavailable")
    days_until = (next_date - as_of_date).days if next_date is not None else None
    return GateResult(passed=earnings_gate(next_date, as_of_date, blackout_days), value=days_until)


def evaluate_macro_gate(as_of_date, session=requests, required_breaches=2):
    try:
        snapshot = fetch_bullion_macro_snapshot(as_of_date, session=session)
    except MacroDataUnavailable:
        return GateResult(passed=False, detail="MacroDataUnavailable")
    breaches = count_macro_breaches(snapshot)
    return GateResult(passed=breaches < required_breaches, value=breaches)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py tests/test_macro_gate.py -v`
Expected: PASS. Some `test_decide_trade_*` tests in `test_pipeline.py` will still be red at this point (Task 4 fixes those) — that's expected; only confirm the wrapper-level tests listed above pass and no *new* failures appeared beyond ones already tracked for Task 4. If `decide_trade`'s own tests already fail here, note it and continue — Task 4 addresses `decide_trade` directly.

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/pipeline.py graywind_strategy/gates/macro_gate.py tests/test_pipeline.py tests/test_macro_gate.py
git commit -m "feat: return GateResult with underlying values from the four pipeline gate wrappers"
```

---

## Task 3: Wire `GateResult` into `evaluate_sector_gates`

**Files:**
- Modify: `graywind_strategy/gates/sector_gates.py`
- Modify: `tests/test_sector_gates.py`

**Interfaces:**
- Consumes: `GateResult` from `graywind_strategy.gate_result` (Task 1).
- Produces: `evaluate_sector_gates(symbol, as_of_date) -> GateResult` whose `.value` is a list of `(sub_gate_name, passed)` tuples for the sub-gates actually evaluated (short-circuits on the first failure, exactly like the current `all(...)` — so `.value` can be a strict prefix of the full sector's gate list, never all of it, when one fails).

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_sector_gates.py`'s six identity-assertion tests with:

```python
# tests/test_sector_gates.py
from datetime import date

from graywind_strategy.gates.sector_gates import (
    SECTOR_GATES,
    energy_stub_gate,
    evaluate_sector_gates,
)


def test_evaluate_sector_gates_passes_untagged_symbol():
    # SPY has no entry in SYMBOL_SECTOR
    result = evaluate_sector_gates(symbol="SPY", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == []


def test_evaluate_sector_gates_passes_tagged_symbol_with_no_registered_gate():
    # AAPL is tagged "tech" in SYMBOL_SECTOR, but SECTOR_GATES has no "tech" entry
    result = evaluate_sector_gates(symbol="AAPL", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == []


def test_evaluate_sector_gates_passes_with_registered_stub():
    # XOM is tagged "energy", which is registered with energy_stub_gate
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is True
    assert result.value == [("energy_stub_gate", True)]


def test_energy_stub_gate_always_true():
    assert energy_stub_gate(symbol="XOM", as_of_date=date(2024, 1, 8)) is True


def test_evaluate_sector_gates_blocks_when_a_registered_gate_returns_false(monkeypatch):
    failing_gate = lambda symbol, as_of_date: False
    monkeypatch.setitem(SECTOR_GATES, "energy", [failing_gate])
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.value == [("<lambda>", False)]


def test_evaluate_sector_gates_requires_all_gates_in_list_to_pass(monkeypatch):
    passing_gate = lambda symbol, as_of_date: True
    failing_gate = lambda symbol, as_of_date: False
    monkeypatch.setitem(SECTOR_GATES, "energy", [passing_gate, failing_gate])
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    assert result.value == [("<lambda>", True), ("<lambda>", False)]


def test_evaluate_sector_gates_short_circuits_after_first_failure(monkeypatch):
    from unittest.mock import MagicMock

    failing_gate = lambda symbol, as_of_date: False
    never_called_gate = MagicMock()
    monkeypatch.setitem(SECTOR_GATES, "energy", [failing_gate, never_called_gate])
    result = evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8))
    assert result.passed is False
    # Only the failing gate made it into value -- never_called_gate never ran,
    # so it's honestly absent from the reading, not silently invented.
    assert result.value == [("<lambda>", False)]
    never_called_gate.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sector_gates.py -v`
Expected: FAIL — `evaluate_sector_gates` still returns a bare `bool`, so `.passed`/`.value` raise `AttributeError`.

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/gates/sector_gates.py -- full replacement
"""Per-sector gate registry: lets a future gate (e.g. an energy oil-price
gate, a tech earnings-surprise gate) apply only to symbols in its sector,
without decide_trade knowing about individual sectors.

Registry contract: every function registered in a SECTOR_GATES list must be
a self-contained evaluator -- same shape as evaluate_vix_gate/
evaluate_macro_gate in pipeline.py. It performs its own I/O and catches its
own XDataUnavailable exception internally, returning a plain bool.
evaluate_sector_gates never sees a raw pure-logic function or an unhandled
exception. evaluate_sector_gates calls each registered gate as
`gate(symbol=symbol, as_of_date=as_of_date)` -- by keyword, not
positionally -- so a registered gate must accept `symbol` and `as_of_date`
as keyword arguments with those exact parameter names, not merely two
positional parameters in that order.

No tag, no registered gate for a symbol's sector, or an empty list are all
treated as "pass" -- a sector caveat is additive risk management, not a
required check (same precedent as earnings_gate: no earnings scheduled ->
allow, not block).

evaluate_sector_gates itself returns a GateResult (see
graywind_strategy.gate_result), not a plain bool -- its .value is the list
of (sub_gate_name, passed) tuples for every sub-gate actually evaluated
this call. Evaluation still short-circuits on the first failure (same as
the old all(...)), so .value can be a strict prefix of the full sector's
gate list, not every registered gate, when one fails.
"""
from graywind_strategy.gate_result import GateResult
from graywind_strategy.sector_config import SYMBOL_SECTOR


def energy_stub_gate(symbol, as_of_date):
    return True


SECTOR_GATES = {
    "energy": [energy_stub_gate],
}


def evaluate_sector_gates(symbol, as_of_date):
    sector = SYMBOL_SECTOR.get(symbol)
    gates = SECTOR_GATES.get(sector, [])
    readings = []
    for gate in gates:
        passed = gate(symbol=symbol, as_of_date=as_of_date)
        readings.append((gate.__name__, passed))
        if not passed:
            return GateResult(passed=False, value=readings)
    return GateResult(passed=True, value=readings)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sector_gates.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/sector_gates.py tests/test_sector_gates.py
git commit -m "feat: return GateResult with per-sub-gate readings from evaluate_sector_gates"
```

---

## Task 4: `decide_trade` collects `gate_readings`; `TradeDecision` gets the new field

**Files:**
- Modify: `graywind_strategy/pipeline.py` (`TradeDecision` dataclass, `decide_trade` function)
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `GateResult` (Task 1), the four wrappers + `evaluate_sector_gates` now returning `GateResult` (Tasks 2-3).
- Produces: `TradeDecision.gate_readings: list` (new field, defaults to `[]` via `field(default_factory=list)` — every existing construction site and every existing test reading only `.action`/`.reason`/`.shares`/`.stop_price`/`.target_price` is unaffected). `decide_trade` populates it with whichever `GateResult`s were actually evaluated this call, in gate-evaluation order (`[vix, sentiment, earnings, macro, sector]`, truncated wherever a gate short-circuits the function), and it stays `[]` whenever `gates_always_pass=True` or `signal != "buy"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py`:

```python
def test_decide_trade_populates_gate_readings_in_order_when_all_gates_pass():
    vix_result = GateResult(passed=True, value=15.0)
    sentiment_result = GateResult(passed=True, value=0.1)
    earnings_result = GateResult(passed=True, value=12)
    macro_result = GateResult(passed=True, value=0)
    sector_result = GateResult(passed=True, value=[])
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: vix_result,
        evaluate_sentiment_gate=lambda **kw: sentiment_result,
        evaluate_earnings_gate=lambda **kw: earnings_result,
        evaluate_macro_gate=lambda **kw: macro_result,
        evaluate_sector_gates=lambda **kw: sector_result,
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "buy"
    assert decision.gate_readings == [vix_result, sentiment_result, earnings_result, macro_result, sector_result]


def test_decide_trade_gate_readings_stops_at_first_blocking_gate():
    vix_result = GateResult(passed=False, value=30.0, detail="above threshold")
    sentiment_mock = MagicMock()
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: vix_result,
        evaluate_sentiment_gate=sentiment_mock,
    ):
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.reason == "vix_gate"
    assert decision.gate_readings == [vix_result]
    sentiment_mock.assert_not_called()


def test_decide_trade_gate_readings_empty_when_gates_always_pass():
    decision = decide_trade(
        symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
        current_price=100.0, account_equity=10000.0,
        pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        gates_always_pass=True,
    )
    assert decision.gate_readings == []


def test_decide_trade_gate_readings_populated_even_on_non_gate_block():
    # drawdown_breaker/pdt_throttle blocks happen AFTER the 5 gates -- the
    # gate readings gathered along the way must still be attached, not
    # discarded just because the eventual block reason is a different check.
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(),
            drawdown_breaker_ok=False, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.reason == "drawdown_breaker"
    assert len(decision.gate_readings) == 5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v -k gate_readings`
Expected: FAIL — `TradeDecision` has no `gate_readings` attribute yet.

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/pipeline.py -- imports: add `field` to the dataclasses import
from dataclasses import dataclass, field
```

```python
# graywind_strategy/pipeline.py -- replace the TradeDecision dataclass with:

@dataclass
class TradeDecision:
    action: str  # "buy" | "hold" | "blocked"
    reason: str
    shares: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    gate_readings: list = field(default_factory=list)
```

```python
# graywind_strategy/pipeline.py -- replace decide_trade's gate-evaluation block
# (the `if not gates_always_pass:` block, currently 5 short-circuit `if not
# evaluate_x_gate(...): return TradeDecision(...)` lines) and thread
# gate_readings through every remaining early return, as follows. Everything
# else in decide_trade (the signature, its docstring's existing paragraphs,
# the risk-check and sizing logic below this block) is unchanged.

    if signal != "buy":
        return TradeDecision(action="hold", reason="no buy signal")

    gate_readings = []
    if not gates_always_pass:
        # Called with keyword arguments (not positional) so that callers/tests
        # can swap these wrappers out for arbitrary-signature stand-ins (e.g.
        # `lambda **kw: True`) without needing to match positional arity.
        vix_result = evaluate_vix_gate(fred_api_key=fred_api_key, as_of_date=as_of_date)
        gate_readings.append(vix_result)
        if not vix_result:
            return TradeDecision(action="blocked", reason="vix_gate", gate_readings=gate_readings)
        sentiment_result = evaluate_sentiment_gate(news_client=news_client, symbol=symbol, as_of_date=as_of_date)
        gate_readings.append(sentiment_result)
        if not sentiment_result:
            return TradeDecision(action="blocked", reason="sentiment_gate", gate_readings=gate_readings)
        earnings_result = evaluate_earnings_gate(symbol=symbol, finnhub_api_key=finnhub_api_key, as_of_date=as_of_date)
        gate_readings.append(earnings_result)
        if not earnings_result:
            return TradeDecision(action="blocked", reason="earnings_gate", gate_readings=gate_readings)
        macro_result = evaluate_macro_gate(as_of_date=as_of_date)
        gate_readings.append(macro_result)
        if not macro_result:
            return TradeDecision(action="blocked", reason="macro_gate", gate_readings=gate_readings)
        sector_result = evaluate_sector_gates(symbol=symbol, as_of_date=as_of_date)
        gate_readings.append(sector_result)
        if not sector_result:
            return TradeDecision(action="blocked", reason="sector_gate", gate_readings=gate_readings)

    if not drawdown_breaker_ok:  # False or None both block -- fail closed on unknown state
        return TradeDecision(action="blocked", reason="drawdown_breaker", gate_readings=gate_readings)
    if not pdt_throttle.can_open_day_trade(as_of_date, pending_count=pending_same_day_trades):
        return TradeDecision(action="blocked", reason="pdt_throttle", gate_readings=gate_readings)

    stop_price = position_sizer.stop_loss_price(current_price, stop_pct)
    if current_price <= 0 or stop_price >= current_price:
        return TradeDecision(action="hold", reason="invalid price for sizing", gate_readings=gate_readings)
    target_price = position_sizer.take_profit_price(current_price, take_profit_pct)
    shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
    shares = round(shares * evaluate_analyst_consensus_multiplier(
        symbol=symbol, as_of_date=as_of_date, current_price=current_price), QTY_DECIMALS)
    if shares <= 0:
        return TradeDecision(action="hold", reason="position size rounds to zero shares", gate_readings=gate_readings)

    return TradeDecision(
        action="buy", reason="all checks passed",
        shares=shares, stop_price=stop_price, target_price=target_price,
        gate_readings=gate_readings,
    )
```

Also add one short paragraph to `decide_trade`'s docstring (append after the existing `pending_same_day_trades` paragraph):

```python
    `gate_readings` on the returned TradeDecision is the ordered list of
    GateResult objects (see graywind_strategy.gate_result) actually
    evaluated this call -- [vix, sentiment, earnings, macro, sector],
    truncated at whichever gate short-circuited the function. Stays empty
    when gates_always_pass=True or signal != "buy" (no gates were ever
    evaluated).
    """
```

- [ ] **Step 4: Run the full pipeline test file to verify everything passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS (every test in the file, including the ones from Task 2)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/pipeline.py tests/test_pipeline.py
git commit -m "feat: collect gate_readings on TradeDecision as decide_trade evaluates each gate"
```

---

## Task 5: `state_store.append_decision_log`

**Files:**
- Modify: `graywind_strategy/state_store.py`
- Modify: `tests/test_state_store.py`

**Interfaces:**
- Produces: `append_decision_log(rows, state_dir=DEFAULT_STATE_DIR)` — appends `rows` (a list of dicts keyed by `DECISION_LOG_FIELDS`) to `<state_dir>/decision_log.csv`, writing the header on first creation. A no-op (no file touched at all) when `rows` is empty. Write failures are not caught — they propagate, matching this project's "log failures raise" convention. `DECISION_LOG_FILENAME = "decision_log.csv"`, `DECISION_LOG_FIELDS = ["timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow", "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates"]` (module-level constants, matching this file's existing `*_FILENAME`/`*_FIELDS` convention).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_state_store.py`:

```python
# tests/test_state_store.py -- add to imports
from graywind_strategy.state_store import append_decision_log  # alongside the existing import line
```

```python
def test_append_decision_log_writes_header_and_row_on_first_call(tmp_path):
    state_dir = str(tmp_path)
    append_decision_log([{
        "timestamp": "2026-01-08T09:35:00-05:00", "symbol": "AAPL", "action": "buy",
        "reason": "all checks passed", "rsi": 45.2, "sma_fast": 101.0, "sma_slow": 99.0,
        "vix": 15.0, "sentiment": 0.1, "days_to_earnings": 12, "macro_breaches": 0, "sector_gates": "[]",
    }], state_dir=state_dir)
    with open(os.path.join(state_dir, "decision_log.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["action"] == "buy"
    assert rows[0]["rsi"] == "45.2"


def test_append_decision_log_appends_across_multiple_calls(tmp_path):
    state_dir = str(tmp_path)
    row = {
        "timestamp": "t1", "symbol": "AAPL", "action": "hold", "reason": "no buy signal",
        "rsi": "", "sma_fast": "", "sma_slow": "", "vix": "", "sentiment": "",
        "days_to_earnings": "", "macro_breaches": "", "sector_gates": "",
    }
    append_decision_log([row], state_dir=state_dir)
    append_decision_log([{**row, "timestamp": "t2"}], state_dir=state_dir)
    with open(os.path.join(state_dir, "decision_log.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["timestamp"] for r in rows] == ["t1", "t2"]


def test_append_decision_log_writes_multiple_rows_from_one_call(tmp_path):
    state_dir = str(tmp_path)
    row = {
        "timestamp": "t1", "symbol": "AAPL", "action": "hold", "reason": "no buy signal",
        "rsi": "", "sma_fast": "", "sma_slow": "", "vix": "", "sentiment": "",
        "days_to_earnings": "", "macro_breaches": "", "sector_gates": "",
    }
    append_decision_log([row, {**row, "symbol": "SERV"}], state_dir=state_dir)
    with open(os.path.join(state_dir, "decision_log.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["symbol"] for r in rows] == ["AAPL", "SERV"]


def test_append_decision_log_is_a_noop_on_empty_rows(tmp_path):
    state_dir = str(tmp_path)
    append_decision_log([], state_dir=state_dir)
    assert not os.path.exists(os.path.join(state_dir, "decision_log.csv"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_state_store.py -v -k decision_log`
Expected: FAIL with `ImportError: cannot import name 'append_decision_log'`

- [ ] **Step 3: Write the implementation**

```python
# graywind_strategy/state_store.py -- add near the other *_FILENAME/*_FIELDS constants
DECISION_LOG_FILENAME = "decision_log.csv"
DECISION_LOG_FIELDS = [
    "timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow",
    "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates",
]
```

```python
# graywind_strategy/state_store.py -- add as a new function, e.g. after save_rebalance_state

def append_decision_log(rows, state_dir=DEFAULT_STATE_DIR):
    """Appends one cycle's decision rows to <state_dir>/decision_log.csv,
    accumulating across every cycle ever run (same append-forever semantics
    as dashboard-data's equity_curve.csv/trade_log.csv, not an overwritten
    snapshot like operational.csv/positions.csv). A no-op on an empty list
    -- most cycles evaluate at least one symbol, but a cycle where every
    symbol is already held (the skip-if-holding guard in live_loop.py)
    legitimately produces zero rows. Any write failure (permissions, full
    disk) propagates -- a missing decision row would produce a misleading
    report later (a trade with no explainable "why"), so this must never
    fail silently.
    """
    if not rows:
        return
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, DECISION_LOG_FILENAME)
    file_exists = os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DECISION_LOG_FIELDS, lineterminator="\n")
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_state_store.py -v`
Expected: PASS (every test in the file)

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/state_store.py tests/test_state_store.py
git commit -m "feat: add append_decision_log for per-cycle decision_log.csv writes"
```

---

## Task 6: Wire decision logging into `live_loop.py`

**Files:**
- Modify: `live_loop.py` (`process_symbol`, `main`)
- Modify: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `append_decision_log` (Task 5), `TradeDecision.gate_readings` (Task 4).
- Produces: `process_symbol(..., rsi=None, sma_fast=None, sma_slow=None, decision_rows=None)` — four new optional keyword parameters, all defaulting to `None` so every existing call site is unaffected. When `decision_rows` is not `None` and `decide_trade` is actually invoked this call (i.e. the symbol wasn't already held), one row is appended to it. `main()` builds a `decision_rows = []` collector per cycle, threads `rsi`/`sma_fast`/`sma_slow` (already-computed columns on `latest`, the per-symbol row `main()` already has) and `decision_rows` into every `process_symbol` call, and calls `append_decision_log(decision_rows, state_dir=state_dir)` in the `finally` block alongside the other per-cycle persistence calls.

**A real trap this task must not fall into:** several existing `test_live_loop.py` tests replace `compute_signals` with `lambda df, **kwargs: df.assign(signal="hold")` — a mock that only adds a `signal` column, not `rsi`/`sma_fast`/`sma_slow`. Once `main()` reads `latest["rsi"]` etc., those mocks must be widened to also assign those three columns, or `main()` raises `KeyError` inside these tests. This affects `test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs`, `test_successful_equity_read_updates_day_and_starting_equity_normally`, `test_main_calls_write_cycle_export_after_save_state`, `test_process_symbol_cycle_passes_confirmation_bars_to_compute_signals`, and `test_main_passes_loaded_tier_pools_to_process_symbol` — every test that calls `live_loop.main()` with a `compute_signals` mock and real (non-empty) `fetch_bars` output. The same four of those five tests (all but `test_main_passes_loaded_tier_pools_to_process_symbol`, which mocks `process_symbol` itself so `decision_rows` never gets appended to) also need `patch("live_loop.append_decision_log")` added to their `with` blocks — without it, `main()`'s real `append_decision_log` call would write an actual `state/decision_log.csv` file into the repo during a test run, since these tests don't override `GRAYWIND_STATE_DIR`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_live_loop.py` (near the other `process_symbol`-focused tests, e.g. after `test_process_symbol_without_collectors_behaves_exactly_as_before`):

```python
def test_process_symbol_appends_decision_log_row_when_decide_trade_runs():
    decision_rows = []
    with patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="buy", reason="all checks passed", shares=10, stop_price=98.0, target_price=103.0),
    ):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="2026-08-15T10:00:00-04:00",
            rsi=45.2, sma_fast=101.0, sma_slow=99.0,
            decision_rows=decision_rows,
        )
    assert decision_rows == [{
        "timestamp": "2026-08-15T10:00:00-04:00", "symbol": "AAPL", "action": "buy",
        "reason": "all checks passed", "rsi": "45.2", "sma_fast": "101.0", "sma_slow": "99.0",
        "vix": "", "sentiment": "", "days_to_earnings": "", "macro_breaches": "", "sector_gates": "",
    }]


def test_process_symbol_decision_row_includes_gate_values_from_gate_readings():
    from graywind_strategy.gate_result import GateResult

    decision_rows = []
    decision = TradeDecision(
        action="blocked", reason="macro_gate",
        gate_readings=[
            GateResult(passed=True, value=15.0),   # vix
            GateResult(passed=True, value=0.05),   # sentiment
            GateResult(passed=True, value=12),     # earnings (days_to_earnings)
            GateResult(passed=False, value=2),     # macro (breaches) -- blocked here, sector never ran
        ],
    )
    with patch("live_loop.decide_trade", return_value=decision):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
            cycle_timestamp="t1", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
            decision_rows=decision_rows,
        )
    row = decision_rows[0]
    assert row["vix"] == "15.0"
    assert row["sentiment"] == "0.05"
    assert row["days_to_earnings"] == "12"
    assert row["macro_breaches"] == "2"
    assert row["sector_gates"] == ""  # never reached -- blocked before the sector gate ran


def test_process_symbol_does_not_append_decision_row_when_skipping_via_held_position():
    decision_rows = []
    symbol_statuses = {}
    open_positions = {"AAPL": _position(stop=98.0, target=103.0, opened_date="2024-01-08")}
    process_symbol(
        symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
        open_positions=open_positions, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
        drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        cycle_timestamp="t1", symbol_statuses=symbol_statuses, decision_rows=decision_rows,
    )
    # decide_trade is never called for an already-held, non-exiting position
    # (the skip-if-holding guard) -- no row to append for it this cycle.
    assert decision_rows == []


def test_process_symbol_without_decision_rows_does_not_raise():
    # decision_rows defaults to None -- must not raise, matching every
    # pre-existing call site in this file.
    with patch(
        "live_loop.decide_trade",
        return_value=TradeDecision(action="hold", reason="no buy signal"),
    ):
        process_symbol(
            symbol="AAPL", signal="buy", current_price=100.0, today=date(2024, 1, 8),
            open_positions={}, equity=10000.0, pdt_throttle=MagicMock(), position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
            trading_client=MagicMock(), drawdown_breaker=MagicMock(),
        )
```

Also add two assertions to the existing `test_main_threads_graywind_state_dir_env_var_into_every_state_call` and `test_main_defaults_graywind_state_dir_to_state_when_env_var_unset` (both currently use `fetch_bars` returning `[]`, so `decision_rows` stays empty but `append_decision_log` is still called unconditionally in the `finally` block):

```python
# tests/test_live_loop.py -- in test_main_threads_graywind_state_dir_env_var_into_every_state_call,
# add `patch("live_loop.append_decision_log") as mock_append_decision_log,` to the `with` block
# (anywhere alongside the other patches), and add to the assertions at the end:
    assert mock_append_decision_log.call_args.kwargs["state_dir"] == "state/small"
```

```python
# tests/test_live_loop.py -- in test_main_defaults_graywind_state_dir_to_state_when_env_var_unset,
# add `patch("live_loop.append_decision_log") as mock_append_decision_log,` to the `with` block,
# and add to the assertions at the end:
    assert mock_append_decision_log.call_args.kwargs["state_dir"] == "state"
```

Widen the `compute_signals` mock in the five tests named in this task's description above to also assign `rsi`/`sma_fast`/`sma_slow`, and add `patch("live_loop.append_decision_log")` to the four of them that reach `decide_trade` with real bars:

```python
# In each of: test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs,
# test_successful_equity_read_updates_day_and_starting_equity_normally,
# test_main_calls_write_cycle_export_after_save_state,
# test_process_symbol_cycle_passes_confirmation_bars_to_compute_signals,
# test_main_passes_loaded_tier_pools_to_process_symbol
# -- replace:
#   patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(signal="hold")),
# with:
    patch("live_loop.compute_signals", side_effect=lambda df, **kwargs: df.assign(
        signal="hold", rsi=50.0, sma_fast=100.0, sma_slow=98.0,
    )),
```

```python
# In the first four of those five (all but test_main_passes_loaded_tier_pools_to_process_symbol,
# which mocks process_symbol itself) -- add to the same `with` block:
    patch("live_loop.append_decision_log"),
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: FAIL — the four new `process_symbol`-level tests fail with `TypeError: process_symbol() got an unexpected keyword argument 'rsi'` (or `decision_rows`); the `main()`-level tests fail with `AttributeError`/`ImportError` on `live_loop.append_decision_log` not existing yet, or `KeyError: 'rsi'` once that's patched in.

- [ ] **Step 3: Write the implementation**

```python
# live_loop.py -- imports: add append_decision_log to the existing state_store import
from graywind_strategy.state_store import (
    append_decision_log, load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state,
)
```

```python
# live_loop.py -- add near the top, alongside WATCHLIST/DASHBOARD_EXPORT_DIR etc.
DECISION_GATE_ORDER = ["vix", "sentiment", "earnings", "macro", "sector"]


def _fmt_decision_value(value):
    return "" if value is None else str(value)


def _decision_log_row(cycle_timestamp, symbol, decision, rsi, sma_fast, sma_slow):
    gate_values = {name: None for name in DECISION_GATE_ORDER}
    for name, result in zip(DECISION_GATE_ORDER, decision.gate_readings):
        gate_values[name] = result.value
    return {
        "timestamp": cycle_timestamp,
        "symbol": symbol,
        "action": decision.action,
        "reason": decision.reason,
        "rsi": _fmt_decision_value(rsi),
        "sma_fast": _fmt_decision_value(sma_fast),
        "sma_slow": _fmt_decision_value(sma_slow),
        "vix": _fmt_decision_value(gate_values["vix"]),
        "sentiment": _fmt_decision_value(gate_values["sentiment"]),
        "days_to_earnings": _fmt_decision_value(gate_values["earnings"]),
        "macro_breaches": _fmt_decision_value(gate_values["macro"]),
        "sector_gates": _fmt_decision_value(gate_values["sector"]),
    }
```

```python
# live_loop.py -- process_symbol's signature: add four new trailing parameters
def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None, tier_pools=None,
                    rsi=None, sma_fast=None, sma_slow=None, decision_rows=None):
```

```python
# live_loop.py -- inside process_symbol, in the `if position is None:` branch,
# immediately after `decision = decide_trade(...)`, add:
        if decision_rows is not None:
            decision_rows.append(_decision_log_row(
                cycle_timestamp=cycle_timestamp, symbol=symbol, decision=decision,
                rsi=rsi, sma_fast=sma_fast, sma_slow=sma_slow,
            ))
```

```python
# live_loop.py -- in main(), alongside the existing `cycle_trades = []` /
# `symbol_statuses = {}` initialization, add:
    decision_rows = []
```

```python
# live_loop.py -- in main()'s per-symbol loop, thread the new fields into
# the process_symbol call:
                process_symbol(
                    symbol=symbol, signal=latest["signal"], current_price=latest["close"],
                    today=today, open_positions=open_positions, equity=equity,
                    pdt_throttle=pdt_throttle, position_sizer=position_sizer,
                    drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
                    fred_api_key=fred_api_key, news_client=news_client,
                    finnhub_api_key=finnhub_api_key, trading_client=trading_client,
                    drawdown_breaker=drawdown_breaker,
                    cycle_timestamp=cycle_timestamp, cycle_trades=cycle_trades,
                    symbol_statuses=symbol_statuses, tier_pools=tier_pools,
                    rsi=latest["rsi"], sma_fast=latest["sma_fast"], sma_slow=latest["sma_slow"],
                    decision_rows=decision_rows,
                )
```

```python
# live_loop.py -- in main()'s `finally:` block, after the existing
# save_rebalance_state(rebalance_state, state_dir=state_dir) call, add:
        append_decision_log(decision_rows, state_dir=state_dir)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: PASS (every test in the file)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, all tests (322 + this plan's new tests)

- [ ] **Step 6: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: write decision_log.csv rows from live_loop, one per decide_trade call"
```

---

## Task 7: `scripts/generate_performance_report.py`

**Files:**
- Create: `scripts/generate_performance_report.py`
- Test: `tests/test_generate_performance_report.py`

**Interfaces:**
- Consumes: `graywind_strategy.backtester.sharpe_ratio`, `max_drawdown`, `win_rate`, `PERIODS_PER_YEAR_15MIN`.
- Produces: `ACCOUNTS` (list of `{"label", "state_dir", "dashboard_dir"}`), `load_account_data(state_dir, dashboard_dir) -> dict | None`, `build_account_report(data) -> dict`, `generate_report() -> dict`, `main()`. Writes `<dashboard_dir>/performance_report.json` per account with data.

**A real field-name mismatch to get right:** `graywind_strategy.backtester.win_rate(trades)` expects each trade dict to have `"action"` (`"buy"`/`"sell"`) and `"shares"` keys — but `trade_log.csv`'s actual columns are `"side"` and `"qty"` (see `graywind_strategy/dashboard_export.py`'s `TRADE_FIELDS`). Calling `win_rate` directly on rows read straight from `trade_log.csv` raises `KeyError`. This script must remap each row (`action=row["side"]`, `shares=float(row["qty"])`, `price=float(row["price"])`) before calling `win_rate`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_generate_performance_report.py
import csv
import json
import os

from scripts.generate_performance_report import (
    ACCOUNTS,
    build_account_report,
    generate_report,
    load_account_data,
    per_symbol_pnl,
    build_block_frequency_notes,
    build_trade_narratives,
)


def _write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


TRADE_FIELDS = ["timestamp", "symbol", "side", "qty", "price", "reason"]
EQUITY_FIELDS = ["timestamp", "equity"]
DECISION_FIELDS = [
    "timestamp", "symbol", "action", "reason", "rsi", "sma_fast", "sma_slow",
    "vix", "sentiment", "days_to_earnings", "macro_breaches", "sector_gates",
]


def test_load_account_data_returns_none_when_dashboard_files_missing(tmp_path):
    result = load_account_data(
        state_dir=str(tmp_path / "state" / "small"),
        dashboard_dir=str(tmp_path / "dashboard-data" / "small"),
    )
    assert result is None


def test_load_account_data_falls_back_gracefully_when_decision_log_missing(tmp_path):
    dashboard_dir = str(tmp_path / "dashboard-data")
    _write_csv(os.path.join(dashboard_dir, "trade_log.csv"), TRADE_FIELDS, [
        {"timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": "all checks passed"},
        {"timestamp": "2026-08-02T10:00:00-04:00", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 105.0, "reason": "stop/target exit"},
    ])
    _write_csv(os.path.join(dashboard_dir, "equity_curve.csv"), EQUITY_FIELDS, [
        {"timestamp": "2026-08-01T09:35:00-04:00", "equity": 10000.0},
        {"timestamp": "2026-08-02T09:35:00-04:00", "equity": 10050.0},
    ])
    result = load_account_data(state_dir=str(tmp_path / "state"), dashboard_dir=dashboard_dir)
    assert result is not None
    assert result["decision_rows"] == []
    assert len(result["trades"]) == 2


def test_build_account_report_computes_metrics_and_narrative(tmp_path):
    dashboard_dir = str(tmp_path / "dashboard-data")
    state_dir = str(tmp_path / "state")
    _write_csv(os.path.join(dashboard_dir, "trade_log.csv"), TRADE_FIELDS, [
        {"timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": "all checks passed"},
        {"timestamp": "2026-08-02T10:00:00-04:00", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 105.0, "reason": "stop/target exit"},
    ])
    _write_csv(os.path.join(dashboard_dir, "equity_curve.csv"), EQUITY_FIELDS, [
        {"timestamp": "2026-08-01T09:35:00-04:00", "equity": 10000.0},
        {"timestamp": "2026-08-01T09:50:00-04:00", "equity": 9800.0},  # a blocked-cycle dip in between
        {"timestamp": "2026-08-02T10:00:00-04:00", "equity": 10050.0},
    ])
    # decision_log.csv lives under state_dir, not dashboard_dir (matches
    # GRAYWIND_STATE_DIR's real layout -- see Task 5/6).
    _write_csv(os.path.join(state_dir, "decision_log.csv"), DECISION_FIELDS, [
        {"timestamp": "2026-08-01T10:00:00-04:00", "symbol": "AAPL", "action": "buy", "reason": "all checks passed",
         "rsi": 45.2, "sma_fast": 101.0, "sma_slow": 99.0, "vix": 15.0, "sentiment": 0.1,
         "days_to_earnings": 12, "macro_breaches": 0, "sector_gates": "[]"},
        {"timestamp": "2026-08-01T09:50:00-04:00", "symbol": "AAPL", "action": "blocked", "reason": "vix_gate",
         "rsi": "", "sma_fast": "", "sma_slow": "", "vix": 30.0, "sentiment": "", "days_to_earnings": "",
         "macro_breaches": "", "sector_gates": ""},
    ])
    data = load_account_data(state_dir=state_dir, dashboard_dir=dashboard_dir)
    report = build_account_report(data)

    assert report["trade_count"] == 2
    assert report["total_pnl"] == 10050.0 - 10000.0
    assert report["win_rate"] == 1.0  # the one round trip (buy 100 -> sell 105) was profitable
    assert report["per_symbol"]["AAPL"]["trades"] == 1  # one round trip
    assert report["per_symbol"]["AAPL"]["pnl"] == (105.0 - 100.0) * 10
    assert len(report["trade_narratives"]) == 2
    buy_narrative = next(n for n in report["trade_narratives"] if n["side"] == "buy")
    assert buy_narrative["rsi"] == "45.2"
    assert "vix=15.0" in buy_narrative["gate_summary"]
    assert any("vix_gate" in note for note in report["block_frequency_notes"])


def test_per_symbol_pnl_pairs_buy_and_sell_round_trips():
    trades = [
        {"timestamp": "t1", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": ""},
        {"timestamp": "t2", "symbol": "AAPL", "side": "sell", "qty": 10, "price": 90.0, "reason": ""},
    ]
    breakdown = per_symbol_pnl(trades)
    assert breakdown == {"AAPL": {"trades": 1, "pnl": -100.0}}


def test_build_block_frequency_notes_summarizes_by_reason():
    decision_rows = [
        {"action": "blocked", "reason": "vix_gate"},
        {"action": "blocked", "reason": "vix_gate"},
        {"action": "buy", "reason": "all checks passed"},
    ]
    notes = build_block_frequency_notes(decision_rows)
    assert len(notes) == 1
    assert "vix_gate" in notes[0]
    assert "67%" in notes[0]


def test_build_trade_narratives_falls_back_when_no_decision_log_match():
    trades = [{"timestamp": "t1", "symbol": "AAPL", "side": "buy", "qty": 10, "price": 100.0, "reason": "all checks passed"}]
    narratives = build_trade_narratives(trades, decision_rows=[])
    assert narratives[0]["gate_summary"] == "no decision-log detail available for this trade"


def test_generate_report_skips_account_with_no_dashboard_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dashboard_dir = str(tmp_path / "dashboard-data")
    _write_csv(os.path.join(dashboard_dir, "trade_log.csv"), TRADE_FIELDS, [])
    _write_csv(os.path.join(dashboard_dir, "equity_curve.csv"), EQUITY_FIELDS, [])
    import scripts.generate_performance_report as gpr
    monkeypatch.setattr(gpr, "ACCOUNTS", [
        {"label": "100k", "state_dir": "state", "dashboard_dir": "dashboard-data"},
        {"label": "small", "state_dir": "state/small", "dashboard_dir": "dashboard-data/small"},
    ])
    report = generate_report()
    assert "100k" in report["accounts"]
    assert "small" not in report["accounts"]
    assert os.path.exists(os.path.join(dashboard_dir, "performance_report.json"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_generate_performance_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.generate_performance_report'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/generate_performance_report.py
#!/usr/bin/env python3
"""One-off script: reads trade_log.csv/equity_curve.csv (dashboard-data/)
and decision_log.csv (state/) for both the $100k and $2k paper accounts,
computes P&L/Sharpe/max-drawdown/win-rate with the backtester's
already-tested pure functions, builds a per-trade "why" narrative by
pairing each trade with its nearest decision_log.csv row, and writes
dashboard-data/performance_report.json (+ dashboard-data/small/... when
that account has data). Run with:

    python3 scripts/generate_performance_report.py

Gracefully skips an account entirely if its dashboard-data/trade_log.csv
or equity_curve.csv doesn't exist yet (matches index.html's own "couldn't
load this account's data" handling) -- decision_log.csv missing is a
softer, per-account fallback: metrics still compute from trade_log.csv/
equity_curve.csv alone, trades just get a generic narrative instead of a
real one, same honest-gap handling as the 6 pre-existing trades that
predate this feature entirely.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from graywind_strategy.backtester import PERIODS_PER_YEAR_15MIN, max_drawdown, sharpe_ratio, win_rate

ACCOUNTS = [
    {"label": "100k", "state_dir": "state", "dashboard_dir": "dashboard-data"},
    {"label": "small", "state_dir": "state/small", "dashboard_dir": "dashboard-data/small"},
]


def _load_csv_rows(path):
    if not os.path.exists(path):
        return None
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_account_data(state_dir, dashboard_dir):
    trades = _load_csv_rows(os.path.join(dashboard_dir, "trade_log.csv"))
    equity_points = _load_csv_rows(os.path.join(dashboard_dir, "equity_curve.csv"))
    if trades is None or equity_points is None:
        return None
    decision_rows = _load_csv_rows(os.path.join(state_dir, "decision_log.csv")) or []
    return {"trades": trades, "equity_points": equity_points, "decision_rows": decision_rows}


def per_symbol_pnl(trades):
    breakdown = {}
    open_by_symbol = {}
    for trade in trades:
        symbol = trade["symbol"]
        if trade["side"] == "buy":
            open_by_symbol[symbol] = trade
        elif trade["side"] == "sell":
            opened = open_by_symbol.pop(symbol, None)
            if opened is not None:
                pnl = (float(trade["price"]) - float(opened["price"])) * float(trade["qty"])
                entry = breakdown.setdefault(symbol, {"trades": 0, "pnl": 0.0})
                entry["trades"] += 1
                entry["pnl"] += pnl
    return breakdown


def _nearest_decision_row(rows_for_symbol, trade_timestamp):
    if not rows_for_symbol:
        return None
    trade_dt = datetime.fromisoformat(trade_timestamp)
    return min(
        rows_for_symbol,
        key=lambda row: abs((datetime.fromisoformat(row["timestamp"]) - trade_dt).total_seconds()),
    )


def build_trade_narratives(trades, decision_rows):
    by_symbol = {}
    for row in decision_rows:
        by_symbol.setdefault(row["symbol"], []).append(row)

    narratives = []
    for trade in trades:
        match = _nearest_decision_row(by_symbol.get(trade["symbol"], []), trade["timestamp"])
        narrative = {
            "timestamp": trade["timestamp"], "symbol": trade["symbol"], "side": trade["side"],
            "qty": trade["qty"], "price": trade["price"], "reason": trade["reason"],
        }
        if match is None:
            narrative["rsi"] = None
            narrative["gate_summary"] = "no decision-log detail available for this trade"
        else:
            narrative["rsi"] = match["rsi"]
            narrative["gate_summary"] = (
                f"vix={match['vix']}, sentiment={match['sentiment']}, "
                f"days_to_earnings={match['days_to_earnings']}, "
                f"macro_breaches={match['macro_breaches']}, sector={match['sector_gates']}"
            )
        narratives.append(narrative)
    return narratives


def build_block_frequency_notes(decision_rows):
    total = len(decision_rows)
    if total == 0:
        return []
    blocked_counts = {}
    for row in decision_rows:
        if row["action"] == "blocked":
            blocked_counts[row["reason"]] = blocked_counts.get(row["reason"], 0) + 1
    notes = []
    for reason, count in sorted(blocked_counts.items(), key=lambda kv: -kv[1]):
        pct = count / total * 100
        notes.append(f"blocked by {reason} on {pct:.0f}% of cycles this period")
    return notes


def build_account_report(data):
    equity_curve = [float(row["equity"]) for row in data["equity_points"] if row["equity"]]
    sharpe = sharpe_ratio(equity_curve, periods_per_year=PERIODS_PER_YEAR_15MIN)
    max_dd = max_drawdown(equity_curve) if equity_curve else 0.0
    mapped_trades = [
        {"symbol": t["symbol"], "action": t["side"], "price": float(t["price"]), "shares": float(t["qty"])}
        for t in data["trades"]
    ]
    win = win_rate(mapped_trades)
    total_pnl = (equity_curve[-1] - equity_curve[0]) if len(equity_curve) >= 2 else 0.0

    return {
        "total_pnl": total_pnl,
        "win_rate": win,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "trade_count": len(data["trades"]),
        "per_symbol": per_symbol_pnl(data["trades"]),
        "trade_narratives": build_trade_narratives(data["trades"], data["decision_rows"]),
        "block_frequency_notes": build_block_frequency_notes(data["decision_rows"]),
    }


def generate_report():
    generated_at = datetime.now(timezone.utc).isoformat()
    report = {"generated_at": generated_at, "accounts": {}}
    for account in ACCOUNTS:
        data = load_account_data(account["state_dir"], account["dashboard_dir"])
        if data is None:
            continue
        account_report = build_account_report(data)
        report["accounts"][account["label"]] = account_report
        os.makedirs(account["dashboard_dir"], exist_ok=True)
        with open(os.path.join(account["dashboard_dir"], "performance_report.json"), "w") as f:
            json.dump({"generated_at": generated_at, **account_report}, f, indent=2)
    return report


def main():
    report = generate_report()
    if not report["accounts"]:
        print("no account data available yet")
        return
    for label, data in report["accounts"].items():
        print(
            f"{label}: {data['trade_count']} trades, P&L ${data['total_pnl']:.2f}, "
            f"win rate {data['win_rate']:.1%}, Sharpe {data['sharpe']:.2f}"
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_generate_performance_report.py -v`
Expected: PASS (every test in the file)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_performance_report.py tests/test_generate_performance_report.py
git commit -m "feat: add generate_performance_report.py for per-account P&L/why reports"
```

---

## Task 8: `generate-performance-report.yml` workflow

**Files:**
- Create: `.github/workflows/generate-performance-report.yml`

**Interfaces:**
- Produces: a `workflow_dispatch`-only GitHub Actions workflow that runs `scripts/generate_performance_report.py` and commits+pushes `dashboard-data/**` changes. Shares `live-trading.yml`'s `concurrency: group: live-cycle` so a manual report run can never race the 15-minute cron's own commit/push of the same `dashboard-data/` tree.

- [ ] **Step 1: Write the workflow file**

```yaml
# .github/workflows/generate-performance-report.yml
name: Generate Performance Report

# Manual only -- a quarterly-cadence artifact doesn't need to regenerate
# every 15-minute live-trading cycle; workflow_dispatch is a deliberate
# button click (or `gh workflow run`), not a schedule.
on:
  workflow_dispatch:

# Lets the built-in GITHUB_TOKEN push graywind's own dashboard-data/*.json.
# No PAT needed -- dashboard data lives in this same repo.
permissions:
  contents: write

# Shares live-trading.yml's own concurrency group: both workflows commit
# and push to the same dashboard-data/ tree on main, so a report run
# overlapping a live-trading cycle's push must queue behind it (or vice
# versa), not race it into a rejected non-fast-forward push.
concurrency:
  group: live-cycle
  cancel-in-progress: false

jobs:
  generate-report:
    runs-on: ubuntu-latest
    steps:
      - name: Check out graywind
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Generate performance report
        run: python3 scripts/generate_performance_report.py

      - name: Commit and push report
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A dashboard-data
          if git diff --cached --quiet; then
            echo "No changes; nothing to commit."
          else
            git commit -m "Generate performance report ($(date -u +%FT%H:%M))"
            git push
          fi
```

- [ ] **Step 2: Validate the YAML parses**

Run: `.venv/bin/pip install pyyaml && .venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/generate-performance-report.yml'))"`
Expected: no output, exit code 0 (matches this project's documented precedent for validating workflow YAML — no automated test suite coverage for workflow files, see `graywind-performance-reports-handoff.md`'s "Verification idioms" section)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/generate-performance-report.yml
git commit -m "feat: add workflow_dispatch workflow to generate and publish the performance report"
```

- [ ] **Step 4: Manual verification after merge (not part of this commit)**

After this plan merges to `main`, run the workflow by hand once (`gh workflow run generate-performance-report.yml` or the Actions tab's "Run workflow" button) and confirm `dashboard-data/performance_report.json` appears in the repo and the job succeeds. Record the result in the next handoff rather than assuming it from the YAML alone.

---

## Task 9: `index.html` performance-report section

**Files:**
- Modify: `index.html`

**Interfaces:**
- Consumes: `dashboard-data/performance_report.json` (+ `dashboard-data/small/performance_report.json`), read via a new `loadJSON` helper alongside the existing `loadCSV`.
- Produces: a new "Performance Report" section per account, rendered after the existing Trade Log section, showing total P&L / win rate / Sharpe / max drawdown, a per-symbol P&L table, block-frequency notes, and the trade-narrative table. Renders a graceful "no report generated yet" empty state when the JSON 404s (report generation is manual — most page loads won't have one yet).

- [ ] **Step 1: Add `loadJSON` and `buildPerformanceReport`**

Add just after the existing `loadCSV` function (around line 310 in the current file):

```javascript
async function loadJSON(path) {
  const res = await fetch(path);
  if (!res.ok) return null;
  return res.json();
}
```

Add a new builder function, placed after `buildTradeLog` (around line 448 in the current file):

```javascript
function buildPerformanceReport(report) {
  if (!report) {
    return `
      <section aria-labelledby="perf-head">
        <div class="section-head"><h2 id="perf-head">Performance Report</h2></div>
        <div class="table-wrap"><div class="empty-state">No performance report has been generated yet.</div></div>
      </section>`;
  }

  const pnlClass = report.total_pnl > 0.005 ? "pos" : report.total_pnl < -0.005 ? "neg" : "flat";

  const symbolEntries = Object.entries(report.per_symbol);
  const symbolRows = symbolEntries.length === 0
    ? `<tr><td colspan="3" style="color:var(--txt-3)">No round-trip trades yet.</td></tr>`
    : symbolEntries.map(([symbol, s]) => `
        <tr>
          <td class="symbol-tag">${symbol}</td>
          <td class="num">${s.trades}</td>
          <td class="num"><span class="${s.pnl >= 0 ? "pos" : "neg"}">${s.pnl >= 0 ? "+" : ""}${money.format(s.pnl)}</span></td>
        </tr>`).join("");

  const narrativeRows = report.trade_narratives.length === 0
    ? `<tr><td colspan="4" style="color:var(--txt-3)">No trades yet.</td></tr>`
    : report.trade_narratives.slice().reverse().map(n => `
        <tr>
          <td>${fmtTime(parseTimestamp(n.timestamp))}</td>
          <td class="symbol-tag">${n.symbol}</td>
          <td><span class="side-tag ${n.side === "buy" ? "buy" : "sell"}">${n.side}</span></td>
          <td style="color:var(--txt-2)">${n.gate_summary}</td>
        </tr>`).join("");

  const noteItems = report.block_frequency_notes.map(note => `<li>${note}</li>`).join("");

  return `
    <section aria-labelledby="perf-head">
      <div class="section-head">
        <h2 id="perf-head">Performance Report</h2>
        <span class="section-note">Generated ${fmtTime(parseTimestamp(report.generated_at))}</span>
      </div>
      <div class="hero-stats">
        <div class="stat">
          <div class="stat-label">Total P&amp;L</div>
          <div class="stat-val ${pnlClass}">${report.total_pnl >= 0 ? "+" : ""}${money.format(report.total_pnl)}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Win Rate</div>
          <div class="stat-val">${(report.win_rate * 100).toFixed(1)}%</div>
        </div>
        <div class="stat">
          <div class="stat-label">Sharpe</div>
          <div class="stat-val">${report.sharpe.toFixed(2)}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Max Drawdown</div>
          <div class="stat-val">${(report.max_drawdown * 100).toFixed(1)}%</div>
        </div>
      </div>
      ${noteItems ? `<ul class="section-note" style="margin-top:12px; padding-left:16px;">${noteItems}</ul>` : ""}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Symbol</th><th class="num">Round Trips</th><th class="num">P&amp;L</th></tr></thead>
          <tbody>${symbolRows}</tbody>
        </table>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Why</th></tr></thead>
          <tbody>${narrativeRows}</tbody>
        </table>
      </div>
    </section>`;
}
```

- [ ] **Step 2: Wire it into `renderAccount` and `loadAccount`**

```javascript
// index.html -- replace renderAccount's signature and innerHTML template:
function renderAccount(accountId, label, containerEl, statusRows, equityRows, tradeRows, performanceReport) {
  if (statusRows.length === 0) {
    renderAccountUnavailable(accountId, label, containerEl, "the live cycle hasn't run yet");
    return;
  }

  containerEl.innerHTML = `
    <h2 class="account-label">${label}</h2>
    <div class="freshness" id="freshness-${accountId}">
      <span class="dot" id="freshness-dot-${accountId}"></span>
      <span id="freshness-text-${accountId}">Loading…</span>
    </div>
    ${buildHero(statusRows, equityRows, tradeRows)}
    <section aria-labelledby="equity-head-${accountId}">
      <div class="section-head"><h2 id="equity-head-${accountId}">Equity Curve</h2></div>
      <div id="chart-wrap-${accountId}"><svg id="chart-${accountId}"></svg></div>
    </section>
    ${buildPositions(statusRows)}
    ${buildTradeLog(tradeRows)}
    ${buildPerformanceReport(performanceReport)}`;

  renderFreshness(accountId, parseTimestamp(statusRows[0].last_cycle_timestamp));
  renderEquityChart(accountId, equityRows);
  window.addEventListener("resize", () => renderEquityChart(accountId, equityRows), { passive: true });
}
```

```javascript
// index.html -- replace loadAccount:
async function loadAccount(accountId, label, dataDir, containerEl) {
  try {
    const [equityRows, tradeRows, statusRows] = await Promise.all([
      loadCSV(`${dataDir}/equity_curve.csv`),
      loadCSV(`${dataDir}/trade_log.csv`),
      loadCSV(`${dataDir}/status.csv`),
    ]);
    // Best-effort, non-blocking: a missing/not-yet-generated report must
    // not prevent the rest of the account from rendering.
    const performanceReport = await loadJSON(`${dataDir}/performance_report.json`);
    renderAccount(accountId, label, containerEl, statusRows, equityRows, tradeRows, performanceReport);
  } catch (err) {
    renderAccountUnavailable(accountId, label, containerEl, err.message);
    document.getElementById(`retry-btn-${accountId}`).addEventListener(
      "click", () => loadAccount(accountId, label, dataDir, containerEl)
    );
  } finally {
    document.getElementById("app").setAttribute("aria-busy", "false");
  }
}
```

- [ ] **Step 3: Manual verification**

No automated test coverage for `index.html` in this project (matches its existing precedent — verified via local server + headless Chrome, same as prior dashboard changes). Do this after Task 7 has produced at least one real `performance_report.json`:

```bash
python3 -m http.server 8000
```

Then use the `headless-chrome-verification` skill (or the `claude-in-chrome` extension) to load `http://localhost:8000/index.html`, confirm:
- With no `performance_report.json` present: the "No performance report has been generated yet." empty state renders under both accounts, no console errors.
- With a `performance_report.json` present (copy a fixture from `tests/test_generate_performance_report.py`'s synthetic data, or run the real script against real `dashboard-data/`): the four stat tiles, per-symbol table, and trade-narrative table render with real numbers, no console errors, no layout overflow on a narrow viewport.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: render the performance report section on the dashboard"
```

---

## Final check

After Task 9, run the full suite once more and confirm the count only grew (never shrank) from the 322 baseline:

```bash
.venv/bin/python -m pytest tests/ -q
```

Then follow `superpowers:requesting-code-review` before merging to `main` — this plan's own established precedent (sub-project 1) was a full whole-branch review with a fix wave and a scoped re-review; propose the same here rather than skipping straight to merge.
