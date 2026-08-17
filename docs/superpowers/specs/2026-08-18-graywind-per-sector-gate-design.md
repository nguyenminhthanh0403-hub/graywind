# Graywind Per-Sector Gate Pattern — Design

**Date:** 2026-08-18
**Status:** approved, not yet implemented
**Prior art:** `docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md` (shipped
the volatility-scaled confirmation-bars filter and the inert `SYMBOL_SECTOR` tags this design
finally consumes), `graywind_strategy/gates/{vix,macro,earnings,sentiment}_gate.py` and their
`evaluate_*_gate` wrappers in `pipeline.py` (the existing gate pattern this design extends to
be sector-aware).

## Goal

`sector_config.py` shipped on 2026-08-17 as inert scaffolding: static `SYMBOL_SECTOR` tags
(tech/energy/health) with no consumer, explicitly meant for "future non-volatility caveats"
like an energy oil-price gate or a tech earnings-surprise gate. This design builds the general
plumbing those future gates will plug into — a per-sector gate registry and dispatcher wired
into `decide_trade` — plus one real (if trivial) instance to prove the plumbing end-to-end.
**Out of scope:** any real sector-specific data source (oil price, earnings-surprise %). Those
are separate future designs; this one only builds the pattern they'll use.

## Architecture

Everything lives in one new file, **`graywind_strategy/gates/sector_gates.py`**:

- `SECTOR_GATES: dict[str, list[Callable]]` — registry mapping sector name to a list of
  evaluator functions. Ships with one entry: `{"energy": [energy_stub_gate]}`.
- `energy_stub_gate(symbol, as_of_date) -> bool` — always returns `True`. A real placeholder
  for a future oil-price gate, not a test fixture.
- `evaluate_sector_gates(symbol, as_of_date) -> bool` — the dispatcher. Looks up
  `SYMBOL_SECTOR.get(symbol)` (imported from `sector_config.py`), then
  `SECTOR_GATES.get(sector, [])`. No tag, no registry entry, or an empty list all mean "pass
  through" — returns `True` with no error. Otherwise every function in the list must return
  `True`; the first `False` short-circuits the dispatcher to `False`.

**Registry contract:** every function registered in a `SECTOR_GATES` list must be a
self-contained evaluator, matching the shape `evaluate_vix_gate`/`evaluate_macro_gate` already
use in `pipeline.py` — it performs its own I/O and catches its own `XDataUnavailable`
exception internally, returning a plain `bool`. `evaluate_sector_gates` never sees a raw
pure-logic function or an unhandled exception. Today's contract is a fixed
`(symbol, as_of_date)` signature. A future real gate needing additional context (an API key,
a session object) will require **explicitly extending this signature** — noted here as a known
future change, not pre-built now.

**Why one sector can allow more than one gate:** decided explicitly during design (not
YAGNI-minimal) so a sector can later carry more than one caveat — e.g. tech eventually getting
both an earnings-surprise gate and something else — without a registry-shape change at that
point.

**Why "pass through silently" on no tag / no registered gate:** matches the existing
`earnings_gate` precedent (no earnings scheduled → allow, not block). A sector caveat is
additive risk management, not a required check — absence of one is not itself a reason to
block a trade.

## Wiring into `pipeline.py`

Add one call inside `decide_trade`'s existing `if not gates_always_pass:` block, after the
four current gates (vix, sentiment, earnings, macro), matching their build-chronological
ordering:

```python
if not evaluate_sector_gates(symbol=symbol, as_of_date=as_of_date):
    return TradeDecision(action="blocked", reason="sector_gate")
```

No new parameters need to be threaded through `pipeline.py`'s call sites in `backtester.py` or
`live_loop.py` — `symbol` and `as_of_date` are already available at every call site.
`gates_always_pass=True` (the existing testing/synthetic-data bypass) skips this gate along
with the other four, automatically, since it's added inside the same `if` block.

## Data Flow

None new this session. `energy_stub_gate` performs no I/O. `evaluate_sector_gates` only reads
two in-memory dicts (`SYMBOL_SECTOR`, `SECTOR_GATES`) — no network calls, no new failure mode.
Real future gates will introduce their own data flow (e.g. an oil-price fetch) as part of
their own design.

## Error Handling

- `energy_stub_gate` cannot fail — no I/O, always `True`.
- `evaluate_sector_gates` has no fallible path today: both dict lookups default to a pass
  (`None`/`[]`) on any miss, so there is nothing to catch at the dispatcher level yet.
- Once a real gate is registered, fail-closed behavior is the *registered gate's own*
  responsibility (its own try/except around its own `XDataUnavailable`, exactly like
  `evaluate_macro_gate` does today) — the dispatcher just trusts the `bool` it receives back,
  the same trust relationship `decide_trade` already has with `evaluate_macro_gate` et al.

## Testing

New `tests/test_sector_gates.py`:
1. Untagged symbol (e.g. SPY) → `evaluate_sector_gates` returns `True`.
2. Tagged symbol whose sector has no registry entry (e.g. a hypothetical "health" tag with no
   registered gate) → `True`.
3. Tagged symbol with the real registered stub (energy → `energy_stub_gate`) → `True`.
4. A mock gate function returning `False`, registered for a test sector → dispatcher returns
   `False`.
5. Two gates registered for one sector, first passes / second fails → `False` — proves "all
   must pass," not just "first must pass."

Extend `tests/test_pipeline.py`'s existing `decide_trade` gate-ordering matrix with one more
case: a mocked sector-gate failure blocks with `TradeDecision(action="blocked",
reason="sector_gate")`, and confirm `gates_always_pass=True` still bypasses it.

No changes needed to `test_backtester.py` or `test_live_loop.py` — the shipped stub always
passes, so existing integration tests keep passing untouched.

## Deferred, not forgotten

- Real energy oil-price gate (replacing `energy_stub_gate`) — needs a data source decision,
  same open question flagged for subsystem 2 (external financial data) in
  `project-graywind-sector-engine` memory.
- Real tech earnings-surprise gate — distinct from the already-shipped, already-generic
  `earnings_gate.py` (which blocks on upcoming-earnings-date blackout, symbol-agnostic); this
  would be about *reacting to a surprise result*, not avoiding the date. Needs an
  actual-vs-estimate data source.
- Extending `evaluate_sector_gates`'s fixed `(symbol, as_of_date)` signature if/when a real
  gate needs more context — deliberately not built ahead of that need.
