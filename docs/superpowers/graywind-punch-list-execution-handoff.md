# Graywind Punch-List Execution — Session Handoff

**Written:** 2026-09-16 · **For:** whoever picks up Graywind next — either to verify this session's tier-pool fix against a real live cycle, make the cross-tier cash-reallocation decision it surfaced, or start on Task 4 (roster flip) or the still-unstarted second half of the manual-trade-panel plan.

## Goal

This session executed most of the 2026-09-15 punch list (`docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md`): investigate-only items got closed, and the $100k account's tier-pool funding gap — long tracked as "fixed" in memory but actually still broken — got properly root-caused and repaired. Before that, two long-open feature branches (MAVIS grounding+auth, manual-trade-panel Tasks 1-5) were merged to `main` at the user's request.

- Plan: `docs/superpowers/plans/2026-09-16-graywind-punch-list.md` (5 tasks; Tasks 1-3 and 5 executed, Task 4 blocked — see below)
- Source handoff this plan implements: `docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md` (2026-09-15, one day older, some of its "live-verified facts" are now superseded by this session's own re-verification — see "What has changed")
- No SDD progress ledger exists for this work — this handoff + `git log` are the source of truth.

## How to resume (do this first)

1. Confirm you're on `main`, up to date with `origin/main`: `git fetch origin && git log --oneline -8`. You should see (top to bottom) `3b01918`, `14a39c2`, `7d828df`, `18545a6` (this session's four commits) sitting directly on top of the live cron's routine `state`/`dashboard-data` update commits — there is no feature branch for this work, it landed straight on `main` after each task's own review+approval.
2. Run the suite to confirm nothing has drifted: `.venv/bin/python -m pytest -q` — expect 584+/584 passing (the `mavis/` subtree is excluded from this via `pytest.ini`; test it separately with `cd mavis && .venv/bin/python -m pytest -q`, expect 36/36).
3. Check whether the live cron has run since this was pushed: `git show origin/main:state/tier_pools.csv`. As of this writing (pushed ~19:47 CDT, past today's 13:00-20:00 UTC market-hours cron window) it **still shows the pre-fix values** (`1,0.0 / 2,51387.633076 / 3,0.0`) — the fix has not yet run against a real cycle. See "What's next" step 1.
4. **Immediate next action:** verify the next live cycle behaves as expected (step 1 below), then read "What has failed / risks / caveats" in full before touching tier_pools.csv or the drift alarm — there's a real, unresolved capital-allocation question sitting underneath this fix that the code deliberately does not answer.

## Current state (active files)

**Branch:** `main`, 4 commits ahead of the live cron's tip when this session started, all pushed to `origin/main`.

**Files created/changed (this session's own commits, oldest first):**
- `18545a6` — `scripts/seed_tier_pools.py`: replaced `pools_are_unfunded()` (required ALL tiers at `$0`) with `zero_tiers()` (seeds each tier individually reading `$0`, leaving others' cash untouched). `tests/test_seed_tier_pools.py` updated to match.
- `7d828df` — same file: added `pools_drifted()` (alarms when a tier's cash+committed value drifts >5% from its target share of total equity — catches "non-zero but wrong," which `zero_tiers()` can't see) and `clamp_seed_to_available_cash()` (prevents the seeding formula from inventing cash a sibling tier has already claimed — see "What has changed" for why this mattered).
- `14a39c2` — `live_loop.py`: `GITHUB_TOKEN` moved into the existing required-credentials guard (`if not all([...])`) instead of being read unchecked afterward. `tests/test_live_loop.py`: 12 pre-existing `main()`-calling tests needed `GITHUB_TOKEN` added to their env patch once it became required, plus one new test for the guard itself.
- `3b01918` — `tests/test_position_sizing.py`: one new pinned regression test, no production code change (punch-list item 5's investigation — see below).
- Also earlier this session (separate commits, already covered by their own handoffs, not re-explained here): merged `feat/mavis-grounding-and-auth` and `feat/manual-trade-panel` into `main`; added root `pytest.ini` to stop root-level `pytest` from trying (and failing) to collect `mavis/tests` with the wrong venv.

**Files later work will modify (untouched so far):**
- `state/tier_pools.csv`, `state/small/tier_pools.csv` — the next live cycle will write to these; don't hand-edit them, let the fix run.
- `docs/superpowers/plans/2026-09-14-graywind-manual-trade-panel.md` — Tasks 6-11 (CLI entrypoint, GitHub Actions workflow, Cloudflare Worker, dashboard action panel, recent-actions feed, deploy/dry-run) are **fully unstarted**. Only Tasks 1-5 shipped in the branch merged this session.

**Scratch workspace / traps:**
- ⚠️ **The pre-fix "tier 2 = $51,387.63" number is real money, not a bug artifact.** Verified directly against `dashboard-data/trade_log.csv`: two genuine closed AAPL round trips (net credits of ~$25,225.57 on 9/1 and ~$26,162.06 on 9/8, both reconciling to the cent against sell-minus-rebuy math). Don't assume a future session should "fix" that number down — it's correct, it's just concentrated in the wrong tier.
- ⚠️ **`docs/superpowers/graywind-manual-trade-panel-handoff.md`** (untracked, still on disk) describes Task 5 as "written and tested but NOT YET COMMITTED" — that was true when it was *written* (2026-09-15) but the branch was fully committed and merged before this session started working on it. Treat that file as historical/stale for commit-state purposes; `git log` is the authority, not that file.
- ⚠️ **`docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md`** (untracked, the 2026-09-15 source of this session's plan) has one live fact this session's own re-verification overrode: it flagged NFCI staleness as ~3 days from tripping `macro_gate.py`'s 14-day ceiling. Re-checked 2026-09-16: FRED published a newer value (2026-09-11) since then, Bullion's cron picked it up, and it's now only 5 days stale. **Not fixed by this session because it wasn't broken** — re-check freshness yourself if it's been more than a few days since 2026-09-16, since NFCI publishes weekly and the gap will grow again.

**Not mine — leave alone:** nothing new; the existing `scripts/fetch_serv_bars.py` (intent-to-added, never staged, per prior sessions' notes) is still sitting there untouched.

## What has changed

- **The $100k account's tier-pool funding gap is now actually root-caused, not just re-patched.** Memory (`project-graywind-tier-pool-funding-gap.md`, now corrected) had this marked "SHIPPED" since 2026-09-01, but that fix only worked for a from-scratch account — once tier 2 legitimately went non-zero from real trading, the old all-or-nothing seeding gate never fired again, and tiers 1/3 stayed stuck at `$0` for two more weeks undetected.
- **A second, more consequential bug was caught mid-fix by an advisor review, before it shipped**: the naive per-tier seed formula would have invented ~$31,000 of phantom cash on the real account (seeding tiers 1/3 as if fresh money existed, unaware tier 2 had already claimed nearly all the real free cash). `clamp_seed_to_available_cash()` fixes this by respecting real cash conservation — on the account as it stands today, that correctly means tiers 1 and 3 get seeded to ~`$0`, which is the honest answer, not a residual bug.
- **A `pools_drifted()` alarm now exists** and will very likely fire on the next live cycle (tier 2 currently sits at ~50.7% of total equity vs. its 20% target) — this is an accurate signal, not a false positive.
- Punch-list item 5 (small-account 50%-cap reachability) is closed as an investigation: the cap is permanently active on the ~$2k account by construction (no tier's pool equity can reach the $2,000 threshold), pinned as a regression test, no code change.
- Orphaned GitHub issue #8 (a `close_issue`-on-expiry silent failure, evidence for punch-list item 6) manually closed.
- Memory corrected: `project-graywind-tier-pool-funding-gap.md`, `project-graywind-critical-review-punch-list.md`, `project-graywind-sector-engine.md` (subsystems 2/3 ruled out), `project-graywind-performance-reports.md` + `project-mavis-cloud-avatar.md` (advising-UI sub-project redirected to MAVIS).
- Full suite: 584/584 (root), 36/36 (`mavis/`).

## What has failed / risks / caveats

- **Nothing has failed in the sense of a broken commit** — everything shipped is tested and reviewed. But:
- **UNVERIFIED against a real live cycle.** As of this writing the fix has been pushed but the market-hours cron window hasn't fired since. Confirm `state/tier_pools.csv` actually changed as expected, and check whether a `tier-pool-alarm` GitHub issue opened (it should — see below).
- **Open capital-allocation decision, not yet made by the user, and not something this code does automatically:** tier 2 holds real cash far in excess of its 20% target while tiers 1/3 sit at effectively `$0`. `pools_drifted()` will keep firing every cycle until a human either moves cash between tiers or deposits more capital. Nothing in this session's fix reallocates that cash — it was deliberately scoped as detection only, per the punch list's own "don't build a framework" guidance. **This is the single most important open thread from this session.**
- **New, accepted alarm-noise tradeoff:** `pools_drifted()` requires `main()` in `seed_tier_pools.py` to call the Alpaca API every cycle now, even when nothing needs seeding (previously it never touched the network in that case). A transient Alpaca outage can now flip an already-healthy account to "unhealthy" for one cycle — self-healing via the existing alarm workflow's auto-close-on-recovery, not a stuck failure, but worth knowing if a `tier-pool-alarm` issue opens and closes on its own shortly after.
- **Task 4 (roster flip, the 6-symbol sector-engine expansion) is fully documented in the plan but was not executed** — it needs `ALPACA_API_KEY`/`ALPACA_API_SECRET` to fetch `data/roster/*.csv` and run `scripts/validate_sector_engine.py`, and this session's shell had neither. Whoever has real Alpaca keys can pick this up directly from the plan's Task 4 steps.
- **The manual-trade-panel plan (merged this session, Tasks 1-5 only) has 6 more tasks entirely unstarted** — CLI entrypoint, GitHub Actions workflow, Cloudflare Worker, dashboard action panel, recent-actions feed, and the deploy/dry-run against the small account. See `docs/superpowers/plans/2026-09-14-graywind-manual-trade-panel.md` (Tasks 6-11) if picking this back up — a completely separate thread from the punch-list work above.

## What's next (ordered)

1. **Verify the fix against a real cycle.** After the next market-hours cron fires (weekdays, 13:07/13:37/...19:37 UTC), check `git show origin/main:state/tier_pools.csv` — tiers 1/3 should still read very close to `$0` (there is currently no real free cash for them), and check `gh issue list -R nguyenminhthanh0403-hub/graywind --label tier-pool-alarm --state all` for a newly opened alarm issue. Both are expected and correct, not failures.
2. **Surface the cross-tier reallocation decision to the user** if it hasn't already been discussed: does the user want to manually move some of tier 2's cash into tiers 1/3 (a one-time rebalance), change the target weights, or leave it as-is and accept the standing alarm? No code should be written for this until the user decides — it's a capital-allocation call, not a bug.
3. **Task 4 (roster flip)** — once real Alpaca credentials are available, follow `docs/superpowers/plans/2026-09-16-graywind-punch-list.md`'s Task 4 steps exactly (fetch roster data → `validate_sector_engine.py` → re-verify the `tier=None` guard at commit `1798308` → confirm no trade-approval issues in flight → flip `WATCHLIST` outside market hours).
4. If returning to the manual-trade-panel effort instead: start at Task 6 in `docs/superpowers/plans/2026-09-14-graywind-manual-trade-panel.md` — read its exact code/tests directly rather than re-deriving.

## Verification idioms used in this project (for the resuming session)

- `.venv/bin/python -m pytest -q` — full root suite, 584/584 as of this handoff (excludes `mavis/` via `pytest.ini`).
- `cd mavis && .venv/bin/python -m pytest -q` — MAVIS's own suite, separate venv, 36/36.
- `git show origin/main:state/tier_pools.csv` / `state/small/tier_pools.csv` — read pushed live state directly, don't trust a local checkout that may be stale.
- `gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open` — check in-flight trade proposals before touching tier/roster config.
- `gh issue list -R nguyenminhthanh0403-hub/graywind --label tier-pool-alarm --state all` — check whether the drift alarm has fired.
- `curl -s "https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/data.json"` — Bullion's live feed; check `history`'s most recent per-field date (fields go stale independently — `_most_recent_value_before()` in `macro_gate.py` walks backward past absent keys correctly, confirmed by direct testing this session).
