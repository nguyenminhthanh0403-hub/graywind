# Graywind Quarterly Performance Reports — Design Spec

**Written:** 2026-08-26 · Sub-project 2 of 3 in the quant-discipline overhaul (see
`docs/superpowers/graywind-quant-discipline-brainstorm-handoff.md`). Sub-project 1 (backtest
gate) shipped and merged to `main` at `2fa4004`. Sub-project 3 (personal-use advising UI) is
separate, not-yet-brainstormed work — this spec covers sub-project 2 only.

## Goal

Give the user quarterly (~3-month cycle) profit/loss reporting with an actual explanation of
*why* — not just numbers, but which gates blocked trades, what signal values triggered entries,
and how each account performed relative to the other. Today's `trade_log.csv` only records a
generic `reason` string (`"all checks passed"`, `"stop/target exit"`) with no per-gate detail,
so there is currently nothing to build a real "why" narrative from.

**Explicitly out of scope:**
- Waiting for a real quarter boundary before anything is usable. Report generation is
  **manually triggerable at any time**, covering whatever history exists — the ~3-month
  cadence is the eventual steady-state, not a gate on seeing a first report. (Real history is
  only 13 days old as of this writing, 6 trades total.)
- Reconstructing "why" for trades that predate this change. The 6 existing trades keep their
  original generic `reason` and are shown honestly as having limited context, not
  retroactively fabricated detail.
- Sub-project 1 (backtest gate, already shipped) and sub-project 3 (advising UI, not started).
- Auto-regenerating the report on the existing 15-minute live-trading cron. A quarterly-cadence
  artifact doesn't need to regenerate every cycle — regeneration is a deliberate,
  `workflow_dispatch`-triggered action.

## Architecture

Three pieces, in dependency order:

1. **`GateResult`** (new, in `graywind_strategy/pipeline.py`) — captures each gate's underlying
   value alongside its pass/fail, with minimal disturbance to `decide_trade`'s existing logic.
2. **`decision_log.csv`** (new, written by `live_loop.py`) — one row per `decide_trade` call,
   every cycle, not just on trades.
3. **`scripts/generate_performance_report.py`** (new) + a `workflow_dispatch` GitHub Actions
   workflow — reads the logs, computes metrics and a why-narrative, publishes to the dashboard.

## `GateResult` — minimal-touch capture

```python
@dataclass
class GateResult:
    passed: bool
    value: object = None
    detail: str = ""

    def __bool__(self):
        return self.passed
```

Each `evaluate_*_gate` wrapper in `pipeline.py` returns a `GateResult` instead of a bare bool,
carrying the value it already computes internally and currently discards:

| Wrapper | `value` | `detail` on failure |
|---|---|---|
| `evaluate_vix_gate` | the fetched VIX close | `"VixDataUnavailable"` if the fetch itself failed |
| `evaluate_sentiment_gate` | the computed sentiment score | `"SentimentDataUnavailable"` |
| `evaluate_earnings_gate` | days until next earnings (or `None`) | `"EarningsDataUnavailable"` |
| `evaluate_macro_gate` | the macro snapshot's breach count | `"MacroDataUnavailable"` |
| `evaluate_sector_gates` | list of `(sub_gate_name, passed)` for that symbol's sector (composite, not a single scalar — this gate is inherently an `all(...)` over a per-sector list) | n/a — no single failure mode |

Because `GateResult.__bool__` returns `passed`, `decide_trade`'s existing lines —
`if not evaluate_vix_gate(...): return TradeDecision(action="blocked", reason="vix_gate")` —
**require zero changes**. `decide_trade` additionally appends each `GateResult` (whether it
passed or short-circuited the function) to a list as it evaluates gates, and passes that list
into the `TradeDecision` it returns. When `gates_always_pass=True` (backtest/synthetic-data
runs), no gates are evaluated and `gate_readings` stays empty — consistent with today's
existing bypass behavior.

## `TradeDecision` — one additive field

```python
@dataclass
class TradeDecision:
    action: str
    reason: str
    shares: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    gate_readings: list = field(default_factory=list)  # new
```

Defaults to an empty list — every existing caller/test reading only `.action`/`.reason`/
`.shares`/`.stop_price`/`.target_price` is unaffected; `backtester.py`'s `run_backtest` doesn't
need to change at all unless/until it wants to also log gate readings for backtest runs (not
required by this spec — backtests already bypass gates via `gates_always_pass=True`).

## `decision_log.csv`

Written by `live_loop.py`, appended once per `decide_trade` call (both the $100k and $2k
accounts each write their own copy, in their respective `GRAYWIND_STATE_DIR`-scoped
directories, same pattern as `trade_log.csv`). Columns:

```
timestamp,symbol,action,reason,rsi,sma_fast,sma_slow,vix,sentiment,days_to_earnings,macro_breaches,sector_gates
```

(`sector_gates` holds `evaluate_sector_gates`'s `GateResult.value` — the serialized
`(sub_gate_name, passed)` list — not a `.detail` string; named to match the other four
gate-value columns' semantics rather than the unrelated `detail`-on-failure field.)

`rsi`/`sma_fast`/`sma_slow` come from the already-computed `signal` dict `decide_trade`
receives as a parameter — no new computation, just logging what's already there. The five
gate-derived columns are populated from `gate_readings` when present, blank when a gate never
ran (e.g. `gates_always_pass=True`, or the function returned before reaching that gate).

## Report generation and publishing

`scripts/generate_performance_report.py` (one-off script, run via `python3
scripts/generate_performance_report.py`, matching this project's existing
`scripts/run_sector_backtest.py`/`scripts/fetch_serv_bars.py` convention):

- Reads `trade_log.csv`, `decision_log.csv`, `equity_curve.csv` for both `state/`
  (default/$100k) and `state/small/` ($2k) — skips the small account gracefully if its files
  don't exist yet, same "couldn't load" pattern the dashboard's `index.html` already uses.
- Computes, per account, over whatever history exists to date: total P&L, win rate, Sharpe
  (reusing `backtester.sharpe_ratio`/`max_drawdown`/`win_rate` — already-tested pure functions,
  no new metric math needed), and per-symbol breakdown.
- Builds a why-narrative: per-trade entries pair each `trade_log.csv` buy/sell with its nearest
  `decision_log.csv` row (matched on symbol + timestamp) to state the RSI/SMA values and which
  gates passed; period-level notes summarize block frequency (e.g. "blocked by vix_gate on 40%
  of cycles this period — VIX elevated most of the window").
- Writes `dashboard-data/performance_report.json` (+ `dashboard-data/small/performance_report.json`
  when the small account has data).

A new `.github/workflows/generate-performance-report.yml`, triggered only by
`workflow_dispatch` (a manual button click, or `gh workflow run`), runs the script and commits
+pushes the output — no local Alpaca credentials needed, since the script only reads
already-committed `state/`/`dashboard-data/` content, no live API calls.

`index.html` adds a new section (rendered from `performance_report.json`, following the
existing `loadCSV`-then-render pattern already used for the other dashboard sections) showing
both accounts side by side, matching the existing dual-account layout.

## Error handling

- `decision_log.csv` write failures should raise, not silently skip — same "don't fail open"
  principle as every other guardrail/log in this project. A missing decision row would produce
  a misleading report later (a trade with no explainable "why").
- The report script must not crash if `decision_log.csv` doesn't exist yet for a given
  timeframe (e.g. first run right after this ships, or the small account before its first
  cycle) — falls back to the generic `trade_log.csv` reason only, same honest-gap handling as
  historical pre-change trades.
- `generate-performance-report.yml`'s failure should not affect the existing `live-trading.yml`
  cron — separate workflow, no shared job dependency.

## Testing

TDD per this project's convention:
- `GateResult.__bool__` and each `evaluate_*_gate` wrapper: unit tests confirming the returned
  object behaves identically to a bare bool in every existing test's `if not evaluate_x_gate(...)`
  usage, plus new tests asserting `.value` carries the right underlying number.
- `decide_trade`: existing tests should pass unmodified (no behavior change to `action`/
  `reason`); new tests assert `TradeDecision.gate_readings` is populated correctly per gate
  outcome, and stays empty when `gates_always_pass=True`.
- `live_loop.py`'s `decision_log.csv` writing: unit test confirming one row is appended per
  cycle per symbol, with the right columns.
- `generate_performance_report.py`: unit tests with synthetic CSV fixtures (not real
  `state/`/`dashboard-data/` content) covering: normal case with both logs present, missing
  `decision_log.csv` (falls back gracefully), missing small-account data entirely.
- `generate-performance-report.yml`: no automated test (matches this project's precedent of
  not testing workflow YAML directly) — validate with `python3 -c "import yaml;
  yaml.safe_load(open(...))"` and a manual `workflow_dispatch` run after merge.
- `index.html`'s new section: manual verification via local `python3 -m http.server` plus
  headless-Chrome screenshots, same as prior dashboard changes.

## Deferred, not forgotten

- Sub-project 3 (personal-use advising UI) — separate future spec.
- Auto-regenerating the report on a schedule — deliberately manual for now; revisit if the
  user wants it automatic once real quarterly cadence is established.
- Attaching `gate_readings` to backtest runs (`run_backtest`) — not required by this spec,
  since backtests already bypass gates entirely via `gates_always_pass=True`.
