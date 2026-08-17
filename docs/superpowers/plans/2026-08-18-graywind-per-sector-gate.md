# Graywind Per-Sector Gate Pattern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a general per-sector gate registry/dispatcher, consumed by `decide_trade`, with one trivial stub gate (energy) proving the plumbing end-to-end.

**Architecture:** One new file, `graywind_strategy/gates/sector_gates.py`, holds a `SECTOR_GATES` registry (sector name → list of self-contained evaluator functions), a stub `energy_stub_gate`, and a dispatcher `evaluate_sector_gates(symbol, as_of_date)`. `pipeline.py`'s `decide_trade` gets one new gate call, ordered after the existing four (vix, sentiment, earnings, macro).

**Tech Stack:** Python, pytest, unittest.mock (matches the rest of `graywind_strategy/gates/` and `tests/test_pipeline.py`).

## Global Constraints

- Registered `SECTOR_GATES` functions must be self-contained evaluators (own I/O, own exception handling, plain `bool` return) — same contract as `evaluate_vix_gate`/`evaluate_macro_gate` in `pipeline.py`. (Spec: "Registry contract.")
- No tag, no registry entry for a sector, or an empty list must all resolve to `True` (pass through), never an error. (Spec: "Why 'pass through silently'.")
- `SECTOR_GATES` values are lists — a sector may hold more than one gate; all must pass. (Spec: "Why one sector can allow more than one gate.")
- No new parameters threaded through `backtester.py`/`live_loop.py` — `symbol` and `as_of_date` are already available at every `decide_trade` call site. (Spec: "Wiring into pipeline.py.")

---

## Task 1: `sector_gates.py` — registry, dispatcher, stub gate

**Files:**
- Create: `graywind_strategy/gates/sector_gates.py`
- Test: `tests/test_sector_gates.py`

**Interfaces:**
- Consumes: `SYMBOL_SECTOR` (dict, already exists in `graywind_strategy/sector_config.py`, symbol → sector tag string, e.g. `{"XOM": "energy", "AAPL": "tech", ...}`; `SYMBOL_SECTOR.get(symbol)` returns `None` for an untagged symbol like `"SPY"`).
- Produces:
  - `SECTOR_GATES: dict[str, list[Callable[[str, date], bool]]]` — module-level registry, ships with `{"energy": [energy_stub_gate]}`.
  - `energy_stub_gate(symbol: str, as_of_date: date) -> bool` — always returns `True`.
  - `evaluate_sector_gates(symbol: str, as_of_date: date) -> bool` — the dispatcher Task 2 will import and call.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sector_gates.py`:

```python
from datetime import date

from graywind_strategy.gates.sector_gates import (
    SECTOR_GATES,
    energy_stub_gate,
    evaluate_sector_gates,
)


def test_evaluate_sector_gates_passes_untagged_symbol():
    # SPY has no entry in SYMBOL_SECTOR
    assert evaluate_sector_gates(symbol="SPY", as_of_date=date(2024, 1, 8)) is True


def test_evaluate_sector_gates_passes_tagged_symbol_with_no_registered_gate():
    # AAPL is tagged "tech" in SYMBOL_SECTOR, but SECTOR_GATES has no "tech" entry
    assert evaluate_sector_gates(symbol="AAPL", as_of_date=date(2024, 1, 8)) is True


def test_evaluate_sector_gates_passes_with_registered_stub():
    # XOM is tagged "energy", which is registered with energy_stub_gate
    assert evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8)) is True


def test_energy_stub_gate_always_true():
    assert energy_stub_gate(symbol="XOM", as_of_date=date(2024, 1, 8)) is True


def test_evaluate_sector_gates_blocks_when_a_registered_gate_returns_false(monkeypatch):
    failing_gate = lambda symbol, as_of_date: False
    monkeypatch.setitem(SECTOR_GATES, "energy", [failing_gate])
    assert evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8)) is False


def test_evaluate_sector_gates_requires_all_gates_in_list_to_pass(monkeypatch):
    passing_gate = lambda symbol, as_of_date: True
    failing_gate = lambda symbol, as_of_date: False
    monkeypatch.setitem(SECTOR_GATES, "energy", [passing_gate, failing_gate])
    assert evaluate_sector_gates(symbol="XOM", as_of_date=date(2024, 1, 8)) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_sector_gates.py -v`
Expected: FAIL/ERROR — `graywind_strategy.gates.sector_gates` does not exist yet.

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/gates/sector_gates.py`:

```python
"""Per-sector gate registry: lets a future gate (e.g. an energy oil-price
gate, a tech earnings-surprise gate) apply only to symbols in its sector,
without decide_trade knowing about individual sectors.

Registry contract: every function registered in a SECTOR_GATES list must be
a self-contained evaluator -- same shape as evaluate_vix_gate/
evaluate_macro_gate in pipeline.py. It performs its own I/O and catches its
own XDataUnavailable exception internally, returning a plain bool.
evaluate_sector_gates never sees a raw pure-logic function or an unhandled
exception.

No tag, no registered gate for a symbol's sector, or an empty list are all
treated as "pass" -- a sector caveat is additive risk management, not a
required check (same precedent as earnings_gate: no earnings scheduled ->
allow, not block).
"""
from graywind_strategy.sector_config import SYMBOL_SECTOR


def energy_stub_gate(symbol, as_of_date):
    return True


SECTOR_GATES = {
    "energy": [energy_stub_gate],
}


def evaluate_sector_gates(symbol, as_of_date):
    sector = SYMBOL_SECTOR.get(symbol)
    gates = SECTOR_GATES.get(sector, [])
    return all(gate(symbol=symbol, as_of_date=as_of_date) for gate in gates)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_sector_gates.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/sector_gates.py tests/test_sector_gates.py
git commit -m "feat: add per-sector gate registry and dispatcher with energy stub"
```

---

## Task 2: Wire `evaluate_sector_gates` into `decide_trade`

**Files:**
- Modify: `graywind_strategy/pipeline.py` (add import near line 18-19, add gate call in `decide_trade` after the existing `evaluate_macro_gate` check)
- Modify: `tests/test_pipeline.py` (import, `_passing_gates()` helper, new failure test, extend the `gates_always_pass` bypass test)

**Interfaces:**
- Consumes: `evaluate_sector_gates(symbol, as_of_date) -> bool` from Task 1's `graywind_strategy/gates/sector_gates.py`.
- Produces: `decide_trade` now also returns `TradeDecision(action="blocked", reason="sector_gate")` when `evaluate_sector_gates` returns `False`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py`, add the import (alongside the existing gate imports near the top):

```python
from graywind_strategy.gates.sector_gates import evaluate_sector_gates
```

Add `evaluate_sector_gates=lambda **kw: True` to the `_passing_gates()` helper so every test currently relying on it stays green once the new gate is wired in:

```python
def _passing_gates():
    return patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: True,
        evaluate_sentiment_gate=lambda **kw: True,
        evaluate_earnings_gate=lambda **kw: True,
        evaluate_macro_gate=lambda **kw: True,
        evaluate_sector_gates=lambda **kw: True,
    )
```

Add a new failure test, mirroring `test_decide_trade_blocks_on_macro_gate_failure`:

```python
def test_decide_trade_blocks_on_sector_gate_failure():
    with patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=MagicMock(return_value=True),
        evaluate_sentiment_gate=MagicMock(return_value=True),
        evaluate_earnings_gate=MagicMock(return_value=True),
        evaluate_macro_gate=MagicMock(return_value=True),
        evaluate_sector_gates=MagicMock(return_value=False),
    ):
        decision = decide_trade(
            symbol="XOM", signal="buy", as_of_date=date(2024, 1, 8),
            current_price=100.0, account_equity=10000.0,
            pdt_throttle=PDTThrottle(), position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(), finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "sector_gate"
```

Extend `test_decide_trade_gates_always_pass_bypasses_gates_and_reaches_risk_checks` to also prove the sector gate is bypassed — add `sector_mock = MagicMock(return_value=False)` alongside the other three mocks, add `evaluate_sector_gates=sector_mock` to the `patch.multiple` call, and add `sector_mock.assert_not_called()` alongside the other `assert_not_called()` lines.

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `python3 -m pytest tests/test_pipeline.py::test_decide_trade_blocks_on_sector_gate_failure -v`
Expected: FAIL — `evaluate_sector_gates` is not yet imported/used in `pipeline.py`, so `decide_trade` never calls the mock and returns `action="buy"` instead of `"blocked"`.

- [ ] **Step 3: Wire the gate into `pipeline.py`**

Add the import next to the other gate imports (after the existing `from graywind_strategy.gates.sentiment_gate import (...)` block, alphabetically before `vix_gate`):

```python
from graywind_strategy.gates.sector_gates import evaluate_sector_gates
```

In `decide_trade`, inside the existing `if not gates_always_pass:` block, add the new check immediately after the `evaluate_macro_gate` check:

```python
        if not evaluate_macro_gate(as_of_date=as_of_date):
            return TradeDecision(action="blocked", reason="macro_gate")
        if not evaluate_sector_gates(symbol=symbol, as_of_date=as_of_date):
            return TradeDecision(action="blocked", reason="sector_gate")
```

- [ ] **Step 4: Run the full pipeline test file**

Run: `python3 -m pytest tests/test_pipeline.py -v`
Expected: all tests pass, including the new `test_decide_trade_blocks_on_sector_gate_failure` and the extended `gates_always_pass` test.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest tests/ -q`
Expected: 194 passed (188 existing + 6 new in `test_sector_gates.py`).

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire evaluate_sector_gates into decide_trade as a 5th blocking gate"
```
