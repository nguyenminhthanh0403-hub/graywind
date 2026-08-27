# Performance Reports Polish — Fix Report

Branch: `graywind-performance-reports-polish`
Base commit before this work: `b533ea4` (docs: add implementation plan for quarterly performance reports)
Baseline test run confirmed before any changes: `355 passed, 0 failed`.

This report covers the 6 parked, non-blocking findings from the completed
quarterly-performance-reports feature (already merged to `main`), fixed per
the task brief. All 6 items are addressed below.

---

## 1. Block-frequency notes denominator is mislabeled

**File:** `scripts/generate_performance_report.py`

**What changed:**
- `build_block_frequency_notes()` (line ~176): added a comment explaining
  that `total = len(decision_rows)` counts per-symbol-per-cycle rows, not
  distinct trading cycles.
- Line ~178: changed the note text from
  `f"blocked by {reason} on {pct:.0f}% of cycles this period"`
  to
  `f"blocked by {reason} on {pct:.0f}% of evaluated decisions this period"`.

**Why:** The old wording claimed a percentage of trading *cycles*, but the
denominator is actually a count of per-symbol-per-cycle decision_log.csv
rows. With a multi-symbol watchlist and the skip-if-holding guard
suppressing rows for already-held symbols, that denominator is neither a
stable nor accurate cycle count. The new wording ("evaluated decisions")
accurately describes what's being measured without overclaiming.

**Verification:**
- Checked `test_build_block_frequency_notes_summarizes_by_reason` in
  `tests/test_generate_performance_report.py` — it only asserts
  `"vix_gate" in notes[0]` and `"67%" in notes[0]`, neither of which
  reference the word "cycles", so no test changes were needed. Confirmed
  it still passes after the wording change (see full suite output below).

---

## 2. `macro_gate()` is dead production code, but has pinned tests

**File:** `graywind_strategy/gates/macro_gate.py`

**What changed:** Added a docstring to `macro_gate()` (line 54) explaining
that `pipeline.py`'s `decide_trade()` calls `count_macro_breaches()`
directly (via its own `evaluate_macro_gate()` helper) instead of the bare
`macro_gate()` function, because it needs the breach count attached to
`gate_readings`, which a plain bool return can't carry. The docstring notes
`macro_gate()` is kept as a tested, reusable pure predicate.

**Why:** Confirmed via `grep -n "macro_gate\|count_macro_breaches"
graywind_strategy/pipeline.py` that `pipeline.py` imports and calls
`count_macro_breaches` directly (not the bare `macro_gate` function).
Per the task brief, this is documentation-only — the function's signature,
return type (bare bool), and its 7 pinned tests in
`tests/test_macro_gate.py` were left untouched.

**Verification:**
- No test changes made or needed (explicitly out of scope).
- `tests/test_macro_gate.py`'s 7 tests still pass unchanged (part of the
  357-pass full suite run below).

---

## 3. Narrative table has no scroll-height cap

**Files:** `index.html`

**What changed:**
- CSS (line 210): extended the existing rule
  `#trade-scroll { max-height: 380px; overflow-y: auto; }`
  to
  `#trade-scroll, #narrative-scroll { max-height: 380px; overflow-y: auto; }`
  — reusing the exact 380px cap without duplicating the rule.
- JS, `buildPerformanceReport()` (around line 540): wrapped the narrative
  `<table>` in `<div id="narrative-scroll">...</div>` inside the existing
  `.table-wrap`, mirroring `buildTradeLog()`'s exact `#trade-scroll`
  pattern. Used a fresh id (`narrative-scroll`) instead of reusing
  `trade-scroll` verbatim, since `buildTradeLog` already claims that literal
  id elsewhere on the same page (an id collision would be invalid HTML and
  `document.getElementById` would only ever find the first match).

**Why:** The narrative table (from the merged performance-report feature)
had no height cap, unlike the pre-existing Trade Log table, and would grow
unbounded with more trades.

**Verification (live, headless Chrome via CDP):**
- Started `python3 -m http.server 8000` from the repo root (backgrounded),
  confirmed `curl` returns HTTP 200 on `http://localhost:8000/index.html`.
- Temporarily inflated `dashboard-data/performance_report.json`'s
  `trade_narratives` to 20 rows (from the real 6) to force overflow, using
  a copy of the real generated report — original file was restored
  afterward (see below); this JSON file is untracked/gitignored-adjacent
  build output, not committed either way.
- Drove headless Chrome via the `headless-chrome-verification` skill's CDP
  driver template (`~/.claude/skills/headless-chrome-verification/templates/cdp_probe.mjs`,
  copied and edited for this page).
- Measured in-page via `getComputedStyle`/`scrollHeight`/`clientHeight`:
  ```
  narrativeExists: true
  narrativeScrollHeight: 773
  narrativeClientHeight: 380
  narrativeOverflowY: "auto"
  narrativeMaxHeight: "380px"
  rowCount: 20
  ```
  `scrollHeight (773) > clientHeight (380)` with `overflow-y: auto` and
  `max-height: 380px` confirms the cap is applied and actually engages
  (the container doesn't grow past 380px even with 20 rows).
- Took a screenshot after `document.getElementById('narrative-scroll').scrollTop = 100`
  — visually confirmed only a partial window of rows is visible inside a
  fixed-height bordered box, with the page footer sitting directly below
  it (not pushed down by table growth).
- Zero console errors/warnings/exceptions were captured via
  `Runtime.consoleAPICalled` / `Runtime.exceptionThrown` listeners during
  the whole page load + interaction.
- Restored the real `dashboard-data/performance_report.json` (the one
  produced by running `scripts/generate_performance_report.py` against
  this worktree's actual `dashboard-data/`/`state/` CSVs) after
  verification, so no test artifacts leaked into the working tree.

---

## 4. `sector_gates` renders as a raw Python repr in the UI

**Files:** `scripts/generate_performance_report.py`,
`tests/test_generate_performance_report.py`

**What changed:**
- Added `import ast` (top of file).
- Added `_format_sector_gates(raw)` helper (after `SELL_EXIT_NARRATIVE`,
  ~line 75): parses the raw `sector_gates` string with `ast.literal_eval`
  inside a `try/except (ValueError, SyntaxError, TypeError)`; on success,
  reformats each `(name, passed)` tuple into `"name:pass"`/`"name:fail"`,
  joined with `;`. On any parse failure, falls back to returning the raw
  string unchanged. An empty/falsy input (`""`) is returned unchanged
  (`if not raw: return raw`) — never fabricates placeholder text.
- `build_trade_narratives()` (~line 156): changed
  `sector={match['sector_gates']}` to
  `sector={_format_sector_gates(match['sector_gates'])}` in the
  `gate_summary` f-string.
- `live_loop.py`'s writing of `decision_log.csv` was **not** touched — the
  raw format on disk is unchanged, matching the task's constraint that this
  is a display-time-only fix.

**Why:** `decision_log.csv`'s `sector_gates` column stores a raw
`str()` of a list of tuples (e.g. `[('energy_stub_gate', True)]`), which
was being interpolated verbatim into the dashboard's "Why" column —
unreadable to a human. `ast.literal_eval` safely parses Python literals
without `eval()`'s arbitrary-code-execution risk, and the try/except
ensures malformed or blank data degrades to the previous raw-string
behavior instead of crashing report generation.

**TDD verification:**
1. Added two new tests to `tests/test_generate_performance_report.py`:
   - `test_build_trade_narratives_formats_sector_gates_as_readable_text` —
     feeds `sector_gates: "[('energy_stub_gate', True)]"` through
     `build_trade_narratives`, asserts the raw repr
     `"('energy_stub_gate', True)"` is NOT in `gate_summary` and
     `"energy_stub_gate:pass"` IS.
   - `test_build_trade_narratives_leaves_empty_sector_gates_unchanged` —
     feeds `sector_gates: ""`, asserts `gate_summary` ends with `"sector="`
     (i.e. stays empty, no fabricated text, no crash).
2. Ran `.venv/bin/python -m pytest tests/test_generate_performance_report.py -q -k sector_gates`
   **before** implementing the fix — confirmed
   `test_build_trade_narratives_formats_sector_gates_as_readable_text` FAILED
   with the raw repr still present in `gate_summary` (the empty-string test
   passed trivially since behavior for `""` was already a no-op pass-through):
   ```
   AssertionError: assert "('energy_stub_gate', True)" not in "vix=15.0, s...ate', True)]"
   1 failed, 1 passed
   ```
3. Implemented `_format_sector_gates()` and the call-site change.
4. Re-ran the same `-k sector_gates` selection and the full suite — both
   new tests pass, no regressions (see full run below).

---

## 5. Pre-existing narrow-viewport CSS Grid overflow

**File:** `index.html`

**What changed:** Added `.account-col { min-width: 0; }` (line 221, right
before the existing `.account-label { margin-top: 0; }` rule). No changes
to `.table-wrap`, `.accounts-grid`, or any table's own CSS, per the task's
explicit constraint.

**Why:** `.accounts-grid` is `display: grid` with `.account-col` as a
direct grid item. Grid items default to `min-width: auto`, which refuses
to shrink below the intrinsic minimum width of their content (here, a
table with `min-width: 480px`) — the classic CSS Grid overflow trap. Adding
`min-width: 0` lets the grid item shrink to the available column width; the
already-present `.table-wrap { overflow-x: auto; }` then handles any
table content wider than that column via internal scrolling.

**Verification (live, headless Chrome via CDP):**
- Same session as item 3's verification. Used
  `Emulation.setDeviceMetricsOverride` to set the viewport to 400×900
  (narrower than the existing `900px` grid-collapse media query breakpoint,
  so `.accounts-grid` was in single-column mode — the overflow trap applies
  in both single- and two-column grid layouts since it's about the grid
  item's own shrink behavior, not the column count).
- Measured:
  ```
  bodyScrollWidth: 400
  docClientWidth: 400
  accountColMinWidth: "0px"
  hasHorizontalOverflow: false
  ```
  `document.body.scrollWidth` equals `document.documentElement.clientWidth`
  exactly (no overflow past the viewport), and `getComputedStyle` on
  `.account-col` confirms `min-width: 0px` is actually applied.
- Screenshot at 400px width visually confirmed: the page itself does not
  scroll horizontally; the Positions table (which is wider than 400px)
  scrolls internally within its own `.table-wrap` (visible as a partially
  cut-off "Unrealized" column at the table's own right edge, not the
  page's edge) — exactly the intended behavior (table-wrap absorbs the
  overflow the grid item no longer blocks).
- Zero console errors during this check (shared console listener from
  item 3's verification run).

---

## 6. Re-verify: does `loadJSON`'s guard actually work end-to-end?

**File:** `index.html`

**Finding:** Re-read `loadJSON` (lines 312–326):
```js
async function loadJSON(path) {
  const res = await fetch(path);
  if (!res.ok) return null;
  try {
    return await res.json();
  } catch (err) {
    // A malformed/partial JSON response must degrade to the "no report
    // generated yet" empty state, not throw up through loadAccount's
    // outer try/catch and wipe the ENTIRE account's render (chart,
    // positions, trade log) -- the adjacent comment in loadAccount already
    // promises a missing/failed report can't take down the rest of the
    // dashboard; this closes the gap where "failed" meant "404" only.
    return null;
  }
}
```
The try/catch is present and correctly wraps only `res.json()` (the
JSON-parsing call, which is what can throw on malformed/partial responses),
returning `null` on parse failure — exactly the guard the prior fix wave
was supposed to add.

**Action taken:** None — already correct. No code change made for this
item.

**Verification:** Static re-read only (no separate live repro of a
malformed-JSON response was constructed, since the code review already
confirms the try/catch correctly wraps `res.json()` and returns `null`,
matching the documented intent in the adjacent comment). The live
headless-Chrome run for items 3/5 also exercised `loadJSON` in its normal
success path against real `dashboard-data/*.json`/`.csv` files with zero
console errors, and against the intentionally-404ing `$2k` account path
(`dashboard-data/small/trade_log.csv` doesn't exist in this worktree),
which exercises `loadJSON`'s `if (!res.ok) return null` branch — confirmed
via screenshot showing the expected "Couldn't load this account's data...
Retry" empty state rather than a crash.

---

## Full test suite output (after all Python changes)

```
$ .venv/bin/python -m pytest tests/ -q
........................................................................ [ 20%]
........................................................................ [ 40%]
........................................................................ [ 60%]
........................................................................ [ 80%]
.....................................................................    [100%]
357 passed, 3 warnings in 1.04s
```

357 = 355 baseline + 2 new tests added for item 4
(`test_build_trade_narratives_formats_sector_gates_as_readable_text`,
`test_build_trade_narratives_leaves_empty_sector_gates_unchanged`).
0 failures. The 3 warnings are pre-existing `DeprecationWarning`s from
third-party packages (`websockets`, `vaderSentiment`), unrelated to this
work.

## Browser verification session cleanup

- The local `python3 -m http.server 8000` process was stopped
  (`pkill -f "http.server 8000"`) — confirmed dead via a follow-up `curl`
  failing to connect.
- All temporary Chrome profile dirs, probe scripts, and screenshots in
  `/tmp` were removed.
- `dashboard-data/performance_report.json` (an untracked, gitignore-adjacent
  generated artifact, not part of the 6 findings' scope) was restored to
  the real report generated from this worktree's actual data before/after
  the temporary 20-row inflation used for the scroll-cap test; it was not
  added to the commit either way.

## Scope discipline

Confirmed untouched, per the task's "What NOT to touch" list:
- Small-account (`$2k`) data path — only observed passively via its
  existing 404 empty-state during browser verification, never modified.
- No GitHub Actions workflow file touched.
- `graywind_strategy/pipeline.py` — not modified (only read, to confirm
  item 2's premise).
- `graywind_strategy/gate_result.py` — not touched.
- `graywind_strategy/gates/sector_gates.py` — not touched.

## Commit(s)

See `git log` — commit hash(es) reported in the final reply to the
delegating agent.
