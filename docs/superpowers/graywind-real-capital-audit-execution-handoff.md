# Graywind — Real-Capital Audit Execution — Session Handoff

**Written:** 2026-08-31 · **For:** whoever picks up Graywind next. 8 of the 9 audit items
are now closed and shipped to `main`; the remaining one is gated behind burn-in, so the
honest next action is mostly **waiting**, not building.

## Goal

Work through the real-capital readiness audit — the punch list that must be cleared before
real money is ever deployed. That audit was written as a review only; this session
executed it. Graywind's purpose is confirmed real-capital deployment, so its items are
mandatory gates, not nice-to-haves.

Authorities (read in this order):
- Prior handoff (the audit itself, still the item numbering authority):
  `docs/superpowers/graywind-real-capital-readiness-handoff.md` — **read its STATUS UPDATE
  block at the top first**; it is the per-item ledger and supersedes the list below it.
- Stopping rules / owner decisions: `docs/superpowers/graywind-real-capital-done-criteria.md`
- The claim being tested: `docs/superpowers/graywind-edge-thesis.md`
- Burn-in pacing authority: `docs/superpowers/burn-in-decision.md`
- No spec/plan exists for this work. It was a punch list, not a feature.

## How to resume (do this first)

1. Confirm where `main` actually is: `git log --oneline -5`. The live cron commits to
   `main` every market cycle, so the tip moves on its own. This session's work is
   `1822d59`, `9b76efc`, `71249c7`.
2. Read the STATUS UPDATE block at the top of
   `docs/superpowers/graywind-real-capital-readiness-handoff.md` — it is the ledger for
   which audit items are done. Trust it and `git log` over anything remembered.
3. Check burn-in progress, which gates everything remaining:
   `git show origin/main:dashboard-data/trade_log.csv | tail -n +2 | wc -l`
4. **Immediate next action:** almost certainly **nothing to build.** Burn-in is at
   **6 of 20 trades** and is the gate on the only open item. Verify the two alarms are
   quiet (`pipeline-alarm` AND `macro-alarm` — see traps below), confirm the trade count,
   and stop. If the owner wants work anyway, the highest-value non-blocked item is the
   $500 re-fund of the small paper account (owner action, not code).

## Current state (active files)

**Branch:** `main`, in sync with `origin/main`. 3 commits from this session on top of the
pre-session tip `1f82cba`.

**Files created / changed (committed in `1822d59`, `9b76efc`, `71249c7`):**
- `graywind_strategy/risk/drawdown_breaker.py` — added `RollingDrawdownBreaker` (weekly
  7d/5%, monthly 30d/10%), plus `build_rolling_breakers()` / `widest_history()` so both
  call sites share one config.
- `graywind_strategy/state_store.py` — `load_equity_history` / `save_equity_history`
  backing the rolling breaker; `equity_history.csv`, one row per calendar day.
- `live_loop.py` — wires the rolling breakers in; adds `_fmt_macro_value` and the
  `unavailable` sentinel for `decision_log.csv`.
- `graywind_strategy/backtester.py` — same rolling breakers, so backtest and live share a
  risk regime.
- `graywind_strategy/pipeline.py` — `MACRO_UNAVAILABLE_DETAIL` shared constant.
- `scripts/check_macro_health.py` — the macro alarm checker.
- `.github/workflows/live-trading.yml` — three steps running that checker and managing a
  `macro-alarm` issue.
- Five new docs in `docs/superpowers/`: `graywind-edge-thesis.md`,
  `graywind-real-capital-done-criteria.md`, `graywind-news-debate-promotion-bar.md`,
  `graywind-standing-design-decisions.md`, `graywind-data-vendor-evaluation.md`.

**Files later work will modify (untouched so far):**
- `graywind_strategy/tier_config.py` — `SYMBOL_TIER` is still `{"AAPL": 2, "SERV": 3}`.
  The only open audit item (diversifying the universe) edits this.
- `tests/test_tier_config.py:11-12` — asserts `SYMBOL_TIER` by exact equality. It **will
  fail the instant any symbol is promoted**; that is expected, update it in the same change.
- `live_loop.py:WATCHLIST` — currently `["AAPL", "SERV"]`. A symbol added to `SYMBOL_TIER`
  but not here is tagged and never traded.

**Scratch workspace / traps:**
- ⚠️ **There are now TWO alarm labels.** `pipeline-alarm` (cron/workflow failing) and the
  new `macro-alarm` (macro gate cannot read its upstream). "No open `pipeline-alarm`
  issue" **no longer means nothing is wrong** — check both. They are separate because the
  existing "Close the alarm issue on success" step closes every open `pipeline-alarm`
  issue each green cycle and would auto-clear the macro one.
- ⚠️ **The local checkout goes stale within hours.** The live cron commits to `main` every
  cycle. Always read live data via `git show origin/main:<path>`, never the working copy.
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` has an **uncommitted
  working-tree diff** inherited from a prior session — the on-disk version is newer than
  the committed one. Trust the disk copy. Not this session's work; left as found.
- ⚠️ Two other git worktrees exist (`.claude/worktrees/agent-ac1e2a7ec9b70e6e3`,
  `.claude/worktrees/graywind-yahoo-analyst-consensus`). Unrelated efforts; leave alone.

**Not mine — leave alone:** `scripts/fetch_serv_bars.py`, `.claude/`, and the untracked
handoffs now moved to `docs/superpowers/archive/`. Everything under `.venv/`,
`__pycache__/`, `alpaca_data/`, `.pytest_cache/`.

## What has changed

- `1822d59` — rolling drawdown breaker + four readiness docs. 412 tests (from 384).
- `9b76efc` — data-vendor evaluation (audit item #8) + the LLM provider decision.
- `71249c7` — macro-gate alarm. **422 tests passing.**

**Audit items closed: 8 of 9.** Only diversifying the live universe remains, and it is
correctly gated behind burn-in.

**Owner decisions settled this session (do not re-open or re-invent these):**
- First real tranche: **$500**. Kill condition: **loses to SPY over burn-in**. Phase-3
  advance bar: **deliberately deferred** until 20 trades exist.
- **`ANTHROPIC_API_KEY` will NOT be set — too costly.** The news-debate shadow gate is
  therefore dormant, not merely un-promoted.
- Long-only is deliberate and documented; no short leg is being built.

**Three findings that reframe the project:**
1. **Tier 1 — 70% of capital — is completely ungated.** `tier1_rebalance.py` has no VIX,
   macro, sentiment, or drawdown check. The entire gate stack protects only the 30% in
   tiers 2/3. This is the basis of the edge thesis and the most important thing to carry
   forward.
2. **The macro gate fails closed on an outage nothing used to alert on.** Now fixed.
3. **The small paper account sits at exactly $2,000.00** — the `small_account_threshold`
   boundary — so it exercises the 3% risk fraction but *not* the 50% position cap that
   $500 of real money will hit. It has also logged zero trades in two weeks.

## What has failed / risks / caveats

- **Nothing has failed.** 422 tests pass; the live paper system is running correctly.
- **UNVERIFIED — the highest-priority caveat.** The rolling drawdown breaker and the macro
  alarm are shipped but have **never run in a real market-hours cycle** (both landed after
  the 2026-08-31 close). Verify on the next trading day: `state/equity_history.csv` should
  appear on `origin/main` and gain one row per day, and the "Check macro-gate health" step
  should report `healthy` in the Actions log. **If `equity_history.csv` never appears, the
  rolling breaker is permanently cold-start and silently inert.**
- **The rolling-breaker thresholds (5% weekly / 10% monthly) are PROVISIONAL**, laddered
  off the 2% daily limit and marked as such in `ROLLING_DRAWDOWN_LIMITS`. They have not
  had owner sign-off.
- **Do not "simplify" two deliberate breaker behaviors:** it is non-latching (a rolling
  baseline moves), and it is permissive on thin history. A fail-closed cold start would
  silently halt all live trading, since `decide_trade` blocks on a falsy
  `drawdown_breaker_ok`.
- **The wiring is mutation-tested.** If you change it, re-run the check: deleting the
  `and all(...)` clause, the `record_equity` loop, or the `equity > 0` guard must each
  fail a specific test. All three did before this was committed.
- **Second-order risk when diversifying:** gating backtest entries reduces trade counts,
  so a candidate can now fall below `MIN_TOTAL_TRADES`, record a failed trial, and
  permanently ratchet the DSR bar for every future candidate. No trials are burned today
  (`validate_symbol_addition` has no callers). Documented at `backtester.py:122`.
- **`validate_symbol_addition()` has no caller.** Item #4 is not "run the existing check" —
  it requires writing a runner script, and the `tier` per symbol is a human input.
- **Burn-in will NOT be complete on 2026-09-14.** At 6/20 trades the rule is 4 weeks **or**
  20 trades, **whichever is later**. Do not let a calendar date end it early.
- **`delegate` is currently unusable.** OpenRouter has withdrawn most of its free catalog
  (five common `:free` slugs now 404 as paid-only; the last routable one 429s). Re-probe
  before planning around it.

## What's next (ordered)

1. **Wait.** Burn-in gates everything. Re-check
   `git show origin/main:dashboard-data/trade_log.csv | tail -n +2 | wc -l` weekly against
   the 20-trade floor.
2. **On the next trading day, verify the two shipped mechanisms actually ran** — see the
   UNVERIFIED caveat above. This is the only genuinely time-sensitive item.
3. **Owner actions (no code):** re-fund the small paper account to **$500** so it exercises
   the real-capital sizing regime; and decide the news-debate gate's fate — the
   recommendation is DeepSeek via OpenRouter (~$2–3/mo, key already in repo secrets), the
   honest alternative is deleting the dormant shadow path.
4. **Investigate the small account's zero trades** before drawing any conclusion from it.
   Possibly sub-`MIN_NOTIONAL` sizing flooring to zero shares.
5. **Only after burn-in clears:** diversify the universe (the last audit item). Write
   `scripts/promote_tier_symbols.py`, validate NVDA/MSFT/XOM/CVX/JNJ/UNH sequentially
   (sector caps depend on run order; tech is nearly full with AAPL), then hand-edit
   `SYMBOL_TIER`, update the exact-equality test, and add to `WATCHLIST`.
6. **Set the Phase-3 advance bar** — deliberately deferred, and required before real
   capital. It is currently the case that the *only* hard gate points at stopping.

## Verification idioms used in this project (for the resuming session)

- **Tests:** `.venv/bin/python -m pytest -q` from the repo root. **Bare `python3` fails
  collection** — the venv has the deps, the system Python does not. 422 passing.
- **Live state:** always `git show origin/main:dashboard-data/trade_log.csv` (and
  `equity_curve.csv`), never the local checkout.
- **Pipeline health:** check for open GitHub issues labelled **both** `pipeline-alarm`
  **and** `macro-alarm`.
- **Macro alarm, locally:** `GRAYWIND_STATE_DIR=<dir> .venv/bin/python
  scripts/check_macro_health.py` — prints the streak and never exits non-zero by design.
- **Workflow YAML:** no test suite covers it; validate by parsing, e.g.
  `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"`.
- **TDD is enforced here** (~5,300 test lines vs ~2,100 strategy lines). Write the failing
  test first; for risk-path changes, mutation-test the wiring afterward.
