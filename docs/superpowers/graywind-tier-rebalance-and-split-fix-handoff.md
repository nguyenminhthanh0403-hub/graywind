# Graywind Tier Rebalance & Split-Adjustment Fix — Session Handoff

**Written:** 2026-09-18 · **For:** whoever picks up Graywind next — either to confirm the tier-pool alarm (#20) actually closes after the next live cycle, decide what (if anything) to do with the NVDA near-miss and the AAPL/SERV informational finding, or continue the still-unstarted manual-trade-panel Tasks 6-11.

## Goal

This session picked up directly from the prior handoff's open thread: the $100k account's tier-2 cash surplus (`pools_drifted()` alarming since 2026-09-16, issue #20) needed a human reallocation decision, and Task 4 (6-symbol roster flip) was blocked on Alpaca credentials. The user supplied real paper-trading credentials mid-session. Along the way, a real data-quality bug was found and fixed (raw/unadjusted stock-split prices corrupting backtest signals), which changed the roster-flip verdict for NVDA specifically and also raised a new, unresolved question about whether the two already-live symbols (AAPL, SERV) would pass today's own validation bar.

- Source handoff this continues: `docs/superpowers/graywind-punch-list-execution-handoff.md` (2026-09-16) — kept, not archived, since it's the immediate predecessor this one links back to.
- That handoff's own predecessor, `docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md` (2026-09-15), has been moved to `archive/` this session — it's now two hops back and fully superseded.
- Plan referenced: `docs/superpowers/plans/2026-09-16-graywind-punch-list.md` (Task 4's exact steps, still the reference for roster-flip mechanics even though the verdict below now supersedes its "blocked" status).
- No SDD progress ledger exists for this work — this handoff + `git log` + the two GitHub issues below are the source of truth.

## How to resume (do this first)

1. Confirm you're on `main`, up to date with `origin/main`: `git fetch origin && git log --oneline -5`. Top two should be `37d7d95` (tier rebalance) and `6180e20` (split-adjustment fix), sitting on top of the live cron's routine `state`/`dashboard-data` commits.
2. Run the suite: `.venv/bin/python -m pytest -q` — expect 585/585 (root; `mavis/` excluded via `pytest.ini`, test separately).
3. **Check whether issue #20 has actually closed yet**: `gh issue view 20 -R nguyenminhthanh0403-hub/graywind`. As of this writing (pushed 2026-09-18T16:41 UTC) the live cron had not re-fired since the push — the issue was still OPEN with a stale pre-fix comment from 2026-09-17T23:02. This is the single most important unverified fact in this handoff — see "What has failed / risks / caveats".
4. **Immediate next action:** confirm #20 closes (or, if it reopens with a *new* post-fix timestamp, the reallocation math needs re-checking — don't assume it's the same stale alarm without checking the timestamp against `6180e20`'s push time).

## Current state (active files)

**Branch:** `main`, 2 commits ahead of the prior handoff's tip, both pushed to `origin/main`.

**Files created/changed (this session's commits, oldest first):**
- `6180e20` — `fetch_alpaca_data.py`: `fetch_bars()` now requests `Adjustment.SPLIT` from Alpaca instead of the default raw/unadjusted prices. This function is shared by `backtest_gate.fetch_backtest_bars` (all backtests) **and by `live_loop.py`'s three live signal-fetch call sites** (lines 732, 859, 1116) — it changes what feeds real trading decisions, not just backtests. No behavior change expected right now (no pending splits on AAPL/SERV), but it's a permanent, global fix, not scoped to any one symbol. `tests/test_fetch_alpaca_data.py` got a new regression test (`test_fetch_bars_requests_split_adjusted_prices`). This commit also bundled `graywind_strategy/backtest_gate_trials.json` (6 candidate trial entries from before the fix existed) and two `state/analyst_consensus.csv` cache rows (NVDA, MSFT) as a side effect of a `git stash`/rebase during the session — harmless, but if you're looking for a clean "just the code fix" commit, it isn't one.
- `37d7d95` — `state/tier_pools.csv`: the $100k account's tier pools reallocated from `1,400.29 / 2,51387.63 / 3,186.96` to `1,21503.923 / 2,20313.978 / 3,10156.989` — a one-time manual rebalance of the account's existing free cash back to the 70/20/10 target (see math in "What has changed"). This is bookkeeping only; no broker-side money movement. The $2k account was already within tolerance (70.06/19.75/10.20%) and was **not** touched.

**Files later work will modify (untouched so far):**
- `state/tier_pools.csv`, `state/small/tier_pools.csv` — the next live cycle will write to these normally; don't hand-edit again unless a new, specific reallocation decision is made.
- `docs/superpowers/plans/2026-09-14-graywind-manual-trade-panel.md` — Tasks 6-11 (CLI entrypoint, GitHub Actions workflow, Cloudflare Worker, dashboard action panel, recent-actions feed, deploy/dry-run) remain **fully unstarted**. Not touched this session.

**Scratch workspace / traps:**
- ⚠️ **Alpaca credentials were exported ad-hoc in this session's shell only** (`export ALPACA_API_KEY=...` / `ALPACA_API_SECRET=...`), never persisted to any file or secret store. A resuming session has no credentials unless the user supplies them again.
- ⚠️ **`docs/superpowers/graywind-mavis-mcp-wrapper-handoff.md`** appeared in the working tree during this session (timestamp ~2026-09-18T16:44 UTC, right around when this session's own work landed) but was **not created by this session** — it looks like concurrent, unrelated work on MAVIS from elsewhere. Leave it alone; it's not part of this handoff's lineage.
- ⚠️ **Four `pending-trade` GitHub issues are open and untouched by this session**: #21 (100k, SERV, tier 3), #22 (small, SERV, tier 3), #23 (small, AAPL, tier 2), #24 (100k, AAPL, tier 2) — all opened 2026-09-17, unresolved as of this writing. They weren't blocking this session's work but will resolve on their own via the normal live-cycle approval flow; check `gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open` for current status before assuming they're still all open.
- ⚠️ `graywind_strategy/backtest_gate_trials.json` now has **7 entries**, not 6 — the original 6 candidate trials (all pre-fix, all failed) plus one more formal NVDA re-run post-fix (also failed, but by only 0.006 Sharpe — see below). None of these entries should be deleted or "corrected"; the trial log is append-only by design (every real attempt counts toward the DSR multiple-testing correction for future candidates, pass or fail).
- **Not mine — leave alone:** `scripts/fetch_serv_bars.py` (intent-to-add, never staged, carried forward from prior sessions' notes, still untouched); the usual pile of untracked local artifacts (`.DS_Store`, `.claude/`, `dashboard-data/performance_report.json`, older untouched handoff `.md` files for unrelated threads like manual-trade-panel, tactical-diversification, tier-allocation, cron-trigger, etc. — none of those are part of this session's lineage).

## What has changed

- **Found and fixed a real data-quality bug**: `fetch_bars()` requested raw/unadjusted Alpaca prices. Confirmed directly against NVDA's actual splits — 2024-06-07→06-10 showed a fake ~90% single-bar "crash" (real: 10:1 split), 2021-07-19→07-20 showed a fake ~75% "crash" (real: 4:1 split). Fixed to request `Adjustment.SPLIT`. Verified: post-fix, both dates are now price-continuous, and the full 2020-2026 series properly shows NVDA's real ~21x rise ($10.39 → $219.57).
- **Re-ran NVDA's roster-flip candidacy with corrected data — verdict flipped from "no edge" to "genuine near-miss".** Pre-fix: sign-flipping fold Sharpes (−0.19, 1.17, −0.27, 0.97), 54% max drawdown, looked like noise. Post-fix (formal trial, `graywind_strategy/backtest_gate_trials.json`): fails on `fold 1: sharpe 0.994 below minimum 1.0` — misses the bar by 0.006. **Still doesn't ship under the existing "all 4 folds must clear" rule**, but this is now the closest near-miss produced by any candidate tested this session, not a rejected-for-cause symbol.
- **Confirmed CVX, JNJ, UNH results were NOT affected by the split bug** — checked each for anomalous single-bar moves; all three had large-but-real market events (CVX: 2020-11-09 vaccine-announcement rally; JNJ: modest -4.9% on 2025-04-01; UNH: -20.3% on 2025-04-17, the real DOJ-investigation/guidance-withdrawal crash). Their original fail verdicts stand.
- **Task 4 (roster flip) is now formally closed as "no expansion"** — all 6 candidates (XOM, CVX, NVDA, MSFT, JNJ, UNH) have a logged failing trial; `WATCHLIST` stays `["AAPL", "SERV"]`. This supersedes the prior handoff's "blocked, needs credentials" status — it's not blocked anymore, it's decided (for now).
- **New, informational-only finding, not acted on**: ran AAPL and SERV (the two already-live symbols) through the same fold-based diagnostic (not the formal `validate_symbol_backtest` — no trial logged) purely to see whether they'd pass their own project's bar today. **Neither would**: AAPL clears 2/4 folds (0.25 and 0.49 fail); SERV clears 1/4 (0.31, 0.74, 0.66 fail). Context: both predate the DSR gate's existence by design — the gate was wired in 2026-08-26, AAPL's first live trade was 2026-08-17, SERV has never executed a single trade. This was surfaced to the user and explicitly **not acted on** — no position was touched, nothing was logged as a formal trial. Purely an open observation for whoever picks this up next.
- **$100k account tier pools reallocated** per the user's explicit go-ahead (see math below). $2k account left untouched (already within tolerance).
- Full suite: 585/585 (root, includes the new split-adjustment regression test). `mavis/` not re-run this session (untouched).

### Tier-rebalance math (for audit)

Using live equity $101,569.89 (both AAPL and SERV flat; only committed position is tier 1's SPY holding):
- `committed(tier1)` = equity − total pool cash = `101,569.89 − 51,974.89` = `49,595.00`
- `tier1_target` = `0.70 × 101,569.89 − 49,595.00` = `21,503.923`
- `tier2_target` = `0.20 × 101,569.89 − 0` = `20,313.978`
- `tier3_target` = `0.10 × 101,569.89 − 0` = `10,156.989`
- Sum = `51,974.89` — exactly conserved, no cash invented or lost.

## What has failed / risks / caveats

- **Nothing has failed in the sense of a broken commit** — full suite passes, both commits are pushed and clean.
- **UNVERIFIED against a real live cycle**, same caveat shape as the prior handoff: the rebalance pushed at 2026-09-18T16:41 UTC, and as of the last check (~16:44 UTC, 3 minutes later) the live cron hadn't fired again yet. Issue #20 was still OPEN showing a comment from *before* the fix (2026-09-17T23:02, against old commit `792c59c`). **Don't mistake that stale comment for a failure of the fix — check the timestamp of the next comment (or the issue's closed state) against `37d7d95`'s push time before concluding anything.**
- **Open decision, not made this session:** what (if anything) to do about AAPL/SERV not clearing today's own validation bar. This is genuinely ambiguous — pulling a live, profitable position over a backtest technicality has real transaction costs and no clear upside; leaving it as-is means the project's own safety bar doesn't actually cover 100% of what's trading. No code changes should be made here without an explicit user decision.
- **NVDA's near-miss (0.994 vs 1.0 threshold) is not a standing recommendation to loosen the gate** — it was reported as-is; no threshold, fold-count, or lookback-window change was made or proposed as code. If a future session wants to revisit whether the strict "all 4 folds must clear" rule is calibrated right, that's a design conversation to have explicitly, not something to change unilaterally off one near-miss.
- **The split-adjustment fix (`6180e20`) also changes live signal data going forward**, since `live_loop.py` shares `fetch_bars()`. No behavior change is expected imminently (no pending splits on AAPL/SERV), but this is a permanent change to what feeds real trading decisions, worth knowing if anything about live signal timing looks different after this lands in a live cycle.

## What's next (ordered)

1. **Confirm issue #20 actually closes** after the next market-hours cron cycle (weekdays, 13:07-20:37 UTC). Check `gh issue view 20 -R nguyenminhthanh0403-hub/graywind` — expect `state: CLOSED`. If it's still open with a *new* comment timestamped after `37d7d95`'s push, the rebalance math needs re-checking against fresh equity (SPY's price moves daily, so the exact target split will drift slightly over time even without another human decision).
2. **Check the four open pending-trade issues** (#21, #22, #23, #24) — `gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open`. These typically resolve within a day or two on their own; no action needed unless one is unexpectedly still open much later.
3. **Decide on the AAPL/SERV informational finding** (see "What has failed" above) — surface to the user if not already discussed further; no code should change here without an explicit decision.
4. **If returning to the manual-trade-panel effort**: start at Task 6 in `docs/superpowers/plans/2026-09-14-graywind-manual-trade-panel.md` — read its exact code/tests directly.

## Verification idioms used in this project (for the resuming session)

- `.venv/bin/python -m pytest -q` — full root suite, 585/585 as of this handoff (excludes `mavis/` via `pytest.ini`).
- `cd mavis && .venv/bin/python -m pytest -q` — MAVIS's own suite, separate venv (not re-verified this session).
- `git show origin/main:state/tier_pools.csv` / `state/small/tier_pools.csv` — read pushed live state directly, don't trust a local checkout that may be stale.
- `gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open` — check in-flight trade proposals before touching tier/roster config.
- `gh issue view 20 -R nguyenminhthanh0403-hub/graywind` — the tier-pool drift alarm; check its state and the timestamp of its latest comment against recent commits before concluding whether a fix has been verified live.
- To re-run a candidate symbol through the real gate: `graywind_strategy.backtest_gate.validate_symbol_backtest(symbol, tier, data_client)` with a real `StockHistoricalDataClient` — this appends a permanent entry to `backtest_gate_trials.json`, so only call it for a real candidate-addition attempt, not exploratory diagnosis (use `fetch_backtest_bars` + `run_backtest` + `split_into_folds` directly for that, as done for the AAPL/SERV informational check this session).
