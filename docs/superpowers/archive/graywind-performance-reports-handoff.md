# Graywind Quant-Discipline Overhaul — Performance Reports Handoff (v2, post-ship)

**Written:** 2026-08-27 · **For:** whoever picks this up next — sub-project 2 is fully shipped
and polished; this handoff exists mainly to hand off sub-project 3 (not started) and flag one
live anomaly (the cron appears to have stopped firing) that needs a human look, not more code.
Supersedes `docs/superpowers/graywind-performance-reports-handoff.md`'s prior version (same
filename, overwritten — the prior version was written mid-work, before the spec was approved;
everything in it is now done).

## Goal

Three-part quant-rigor overhaul for Graywind. Sub-project 1 (backtest gate) and sub-project 2
(quarterly performance reports, this handoff's subject) are both **shipped and pushed**.
Sub-project 3 (personal-use advising UI) has **no spec yet** — that's the actual next work.

- Spec (sub-project 2): `docs/superpowers/specs/2026-08-26-graywind-performance-reports-design.md`
- Plan (sub-project 2): `docs/superpowers/plans/2026-08-26-graywind-performance-reports.md`
- No plan/spec exists yet for sub-project 3.

## How to resume (do this first)

1. Confirm state: `git log --oneline -1` should show `527e983` as `HEAD` on `main`, and
   `git status -sb` should show `main...origin/main` with **no** ahead/behind count (fully
   synced — this was pushed, not just committed locally).
2. Run the test suite: `.venv/bin/python -m pytest tests/ -q` → expect **357 passed, 0 failed**.
   If this number is different, something changed since this handoff was written — trust the
   test run over this document.
3. **Immediate next action:** there is no in-progress code work to resume for sub-project 2 —
   it's done. The two real things to look at are (a) the cron anomaly below, which needs a
   human check of the GitHub Actions UI / billing page, not more code, and (b) starting
   `superpowers:brainstorming` for sub-project 3 if that's the priority now.

## Current state (active files)

**Branch:** `main`, fully pushed, `HEAD` at `527e983`. No open branches, no worktrees left
behind (`git worktree list` should show only the main checkout).

**What sub-project 2 shipped (all committed, all on `origin/main`):**
- `graywind_strategy/gate_result.py` — new `GateResult(passed, value, detail)` dataclass, its
  own leaf module (no project imports) specifically to avoid a circular import with
  `gates/sector_gates.py`.
- `graywind_strategy/pipeline.py` — the four gate wrappers (`evaluate_vix_gate`/
  `evaluate_sentiment_gate`/`evaluate_earnings_gate`/`evaluate_macro_gate`) and
  `evaluate_sector_gates` (in `gates/sector_gates.py`) now return `GateResult` instead of a bare
  bool. `decide_trade`'s `TradeDecision` gained an additive `gate_readings` field — every
  existing call site/test that doesn't pass it is unaffected.
- `graywind_strategy/state_store.py` — new `append_decision_log(rows, state_dir=...)`, appends
  to `<state_dir>/decision_log.csv` (accumulates forever, same as `trade_log.csv`/
  `equity_curve.csv`; never overwrites).
- `live_loop.py` — writes one `decision_log.csv` row per `decide_trade` call, every cycle, for
  both accounts (their own `GRAYWIND_STATE_DIR`-scoped copy).
- `scripts/generate_performance_report.py` — new, reads `decision_log.csv` (from `state_dir`)
  + `trade_log.csv`/`equity_curve.csv` (from `dashboard_dir` — **these are two different
  directory trees, don't conflate them**), computes P&L/Sharpe/win-rate/max-drawdown/per-symbol
  breakdown, builds a "why" narrative, writes `dashboard-data/performance_report.json`
  (+ `small/` when that account has data).
- `.github/workflows/generate-performance-report.yml` — new, `workflow_dispatch`-only, shares
  `live-trading.yml`'s `concurrency: group: live-cycle` so a manual report run can't race the
  15-min cron's push. **Never run against real data yet** — nobody has clicked "Run workflow"
  on it since it was written. Doing that once, during market hours after a real trading history
  exists, is a reasonable next step whenever someone wants to see this feature actually work
  end-to-end on production data.
- `index.html` — new "Performance Report" section, both accounts, graceful empty state when no
  report has been generated yet.

**Polish follow-up (same day, commit `944abdc`→`527e983`), all parked minors from the final
review now fixed:** the CSS Grid narrow-viewport overflow (`.account-col` now has
`min-width: 0`), `block_frequency_notes`' mislabeled "% of cycles" text, `macro_gate()`'s
dead-production-code docstring note, `sector_gates` no longer rendering as a raw Python repr in
the UI, the narrative table's missing scroll-height cap. All independently reviewed clean, real
headless-Chrome verification (not just static checks) confirmed the CSS/scroll fixes render
correctly.

**Scratch workspace / traps:**
- ⚠️ `scripts/fetch_serv_bars.py` — still untracked, uncommitted, unrelated to both
  sub-projects, carried forward across multiple handoffs now. Still needs the user's own
  `ALPACA_API_KEY`/`SECRET` to run — no session has these.
- ⚠️ **The live-trading cron appears to have stopped firing.** As of 2026-08-27T17:15 UTC
  (well within the 13:30–20:00 UTC market-hours window, on a weekday), the workflow's run
  history (`curl -s "https://api.github.com/repos/nguyenminhthanh0403-hub/graywind/actions/workflows/live-trading.yml/runs?per_page=10"`)
  shows **zero runs since run #95 at 2026-08-26T23:35:34Z** — the previous day. The workflow's
  own `state` field reports `"active"` (not disabled), so this isn't a simple accidental
  disable. This was NOT touched by anything in this session — no commit here modified
  `live-trading.yml`'s trigger. Possible causes, none confirmed: a GitHub Actions outage, a
  minutes-quota exhaustion on a free-tier account, or something in the GitHub UI a browser
  session would surface that the API doesn't. **This needs a human look at the Actions tab in
  a browser**, not more code — a resuming session should re-check the run history first
  (the anomaly may have already resolved itself) before assuming anything is broken in code.
- ⚠️ `state/small`/`dashboard-data/small` still don't exist on `origin/main`. The
  `live-cycle-small` job was added 2026-08-26T19:05 UTC; every run since then landed outside
  market hours, and now (per the point above) the cron isn't running at all — so this is
  doubly blocked. Not a code issue on its own, but it's now entangled with the cron anomaly:
  if the cron is actually broken, this will never resolve on its own.

**Not mine — leave alone:** `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` —
untracked, belongs to a different concurrent session's sub-project-3-adjacent work (a
news-interpretation thread). Same note carried forward from prior handoffs in this lineage —
still true, still not touched.

## What has changed

**Sub-project 2 (performance reports) — fully shipped, merged, pushed, and polished.** Built
via `superpowers:writing-plans` → `superpowers:subagent-driven-development`, 9 tasks, every
task's own review came back clean on the first pass (the plan's upfront research — reading the
real codebase before writing tasks, not just the spec — caught most cross-task traps ahead of
time: a circular-import risk, a `trade_log.csv` field-name mismatch, a `compute_signals`-mock
`KeyError` trap across 5 existing tests). The final whole-branch review (Opus) found 1 Critical
+ 5 Important: an unbounded narrative-matching bug that could attribute a trade to a different
day's — possibly blocked — decision, and paired every sell trade with an unrelated buy
evaluation (since `decision_log.csv` never logs exits); a Sharpe figure inflated ~1.6x by
reusing the backtester's 15-minute-bar annualization constant against a non-uniform live
series; an unlabeled mismatch between mark-to-market total P&L and realized-only per-symbol
P&L; RSI/SMA captured but never rendered; an earnings-gate blank-vs-never-reached ambiguity. One
fix wave addressed all 6 (including a re-surfaced `loadJSON` parse-guard minor), scoped
re-review confirmed all ADDRESSED with no new breakage. Merged to `main`, pushed at `b533ea4`.

**Same-day polish pass** (user explicitly asked to fix the parked minors after reviewing the
completion summary) addressed all 5 remaining non-blocking findings — see "Current state"
above. Reviewed clean, merged, pushed at `527e983`.

322 tests at the start of this session → **357 tests, all passing, at the end.**

## What has failed / risks / caveats

- **Nothing in the shipped code has failed.** All 357 tests pass; every review (9 task-level +
  1 final whole-branch + 1 fix-wave re-review + 1 polish-pass review) came back clean.
- **UNVERIFIED, live, needs a human check:** the cron anomaly above. This is the one thing in
  this handoff that isn't a "next task," it's a "go look at something" item.
- **UNVERIFIED:** the new `generate-performance-report.yml` workflow has never actually been
  run — its YAML was validated (`yaml.safe_load`) and its script has full test coverage against
  synthetic fixtures, but nobody has clicked the button against real production data yet.
- **Decisions carried forward from this lineage, don't re-litigate:**
  - Report generation is manual-trigger via `workflow_dispatch`, never the 15-min cron.
  - The narrative-match tolerance (same-day only; sells never matched against `decision_log.csv`
    at all) is load-bearing — it's the fix for the Critical finding above. Don't widen it or
    "simplify" it away without understanding why it's there.
  - The published Sharpe is deliberately **unannualized** ("Sharpe (period)" in the UI) — don't
    reintroduce `backtester.PERIODS_PER_YEAR_15MIN` here; that constant assumes uniform 15-min
    bars, which the live equity curve's actual cadence (~41 min median gap, with multi-day
    weekend gaps) doesn't have.
  - Both accounts ($100k + $2k) reported side by side; published to the public dashboard, not a
    private file (user's own explicit choice against the original recommendation).

## What's next (ordered)

1. **Check the GitHub Actions cron anomaly first** — open the repo's Actions tab in a browser
   (not the API) and look for anything the API summary above wouldn't show (a paused workflow
   notice, a billing/quota banner, an outage note). Re-run the API check
   (`curl -s ".../actions/workflows/live-trading.yml/runs?per_page=5"`) first in case it's
   already resolved itself by the time you read this.
2. **Separate, independent, whenever convenient:** ask the user to run
   `python3 scripts/fetch_serv_bars.py` themselves (own Alpaca credentials required).
3. **Once the cron is confirmed healthy and a real in-hours cycle has landed for the small
   account:** do one manual `workflow_dispatch` run of `generate-performance-report.yml` to see
   the whole pipeline work end-to-end against real production data for the first time, and
   spot-check the published `dashboard-data/performance_report.json` (+ `small/`) and the
   dashboard's new section against what you'd expect.
4. **Sub-project 3 (personal-use advising UI) is next** in the original decomposition — no spec
   exists, needs its own `superpowers:brainstorming` session. One thing already answered from
   the original decomposition: personal-use only, no auth/compliance surface needed.

## Verification idioms used in this project (for the resuming session)

- Full test suite: use the project's `.venv`, not system `python3` —
  `.venv/bin/python -m pytest tests/ -q`. 357 tests as of `527e983`.
- Local checkouts drift stale fast (a 15-min live cron — when it's running — auto-commits to
  `main`) — `git fetch origin main` and diff against `origin/main`, or read straight from a ref
  with `git show origin/main:<path>`.
- GitHub Actions run history (works unauthenticated, public repo, no `gh` CLI needed):
  ```
  curl -s "https://api.github.com/repos/nguyenminhthanh0403-hub/graywind/actions/workflows/live-trading.yml/runs?per_page=10" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('total_count:', d['total_count']); [print(r['run_number'], r['status'], r['conclusion'], r['event'], r['created_at']) for r in d['workflow_runs']]"
  ```
  Check the workflow's own enabled/disabled state with
  `curl -s ".../actions/workflows/live-trading.yml"` and read the `"state"` field.
  Per-job/per-step breakdown: `curl -s ".../actions/runs/<run_id>/jobs"`.
- Repo tree contents without cloning: `curl -s "https://api.github.com/repos/<owner>/<repo>/contents/<path>"`.
- Listing or setting repo secrets requires real auth (`gh` CLI or a token) — not available on
  this machine; unauthenticated calls to the secrets API return 401.
- Live public dashboard: `https://nguyenminhthanh0403-hub.github.io/graywind/`.
- This project follows TDD (red/green) for `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py`/`risk/`/`live_loop.py`/`backtest_gate.py`/`generate_performance_report.py`
  changes; workflow YAML and `index.html` changes have no automated coverage — validate YAML
  with `python3 -c "import yaml; yaml.safe_load(open('<path>'))"` (needs `pyyaml`, not in the
  base venv — `pip install pyyaml` into `.venv` first) and verify HTML/JS changes with a local
  `python3 -m http.server` plus headless-Chrome checks (real console/DOM verification, not just
  reading the diff — this project has caught real bugs this way, e.g. this session's own
  narrative-fabrication Critical finding was confirmed by an actual reproduction, not just
  code review).
- **Always check `git branch -a`, `git worktree list`, and `git log --all --oneline` for
  unmerged/leftover work** before starting — established precedent in this project's history (a
  fully-built, tested, unmerged branch once sat untouched for 5 days with zero mention
  anywhere). This session left no worktrees or branches behind (both were merged, cleaned up,
  and pushed) — if `git worktree list` shows anything beyond the main checkout when you read
  this, it's from a session after this one, not this one.
