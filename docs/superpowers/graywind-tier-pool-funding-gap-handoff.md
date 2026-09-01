# Graywind — Tier Pool Funding Gap — Session Handoff

**Written:** 2026-09-01 · **For:** whoever picks up Graywind next. This session was meant to
be a burn-in check-in on the real-capital audit; it found a live bug instead. **The
prior handoff's "wait for burn-in" is no longer the right next action** — burn-in cannot
progress while tiers 2/3 are starved on both accounts.

**RESOLVED 2026-09-01, same day — `scripts/seed_tier_pools.py` shipped.** Fetches live
equity + open positions from Alpaca, computes the 70/20/10 split netted against
already-committed positions, and writes it once (idempotent — only fires when all three
tiers read exactly `$0`). Wired into both `live-cycle` and `live-cycle-small` jobs in
`.github/workflows/live-trading.yml`, right after `live_loop.py` runs. Raises a separate
`tier-pool-alarm` GitHub issue (per account) if a pool is ever found unfunded and can't
be seeded (missing credentials, Alpaca API error) — same separate-label pattern as
`macro-alarm`, for the same reason (the generic `pipeline-alarm` auto-close would
otherwise silently clear it on the next green cycle). 12 new tests, 434/434 suite
passing. **Not yet verified against a real cycle** — see "What's next" at the bottom for
the actual confirmation step once this merges and a cycle runs.

**A second, deeper finding surfaced while designing the fix — deliberately NOT fixed
here, scope stayed to funding, not redesign:** seeding `tier_pools[1]` only fixes the
*initial* bootstrap. `run_tier1_rebalance` computes
`tier1_equity = tier_pools[1] + current_SPY_value` and, since `TIER1_SYMBOL_WEIGHTS`
has exactly one symbol at weight 1.0, `target_value` for that symbol is always
`tier1_equity × 1.0 == tier1_equity` by construction — so drift is structurally ~0
**once the seeded pool cash is invested**, regardless of whether the account's true
total equity has since grown or shrunk relative to tiers 2/3. Tier 1 never re-checks
itself against real total account equity going forward; it only ever compares itself to
its own past accumulation. **Practical effect:** the seed fix makes tier 1 correctly
sized *today*; it will silently drift away from a true 70%-of-total-equity target over
following months with no detection, the same "looks healthy, isn't" shape as the
original bug. Fixing this needs `compute_rebalance_orders` (or its caller) to receive
real total account equity, not `tier_pools[1] + committed`, as its equity basis — a
distinct, larger change than this fix, not built here. Worth a future bounded task.

## Goal

Resume from `docs/superpowers/graywind-real-capital-audit-execution-handoff.md`, whose
"immediate next action" was: verify the two newly-shipped alarms are quiet, confirm burn-in
trade count, and stop. That verification surfaced a real, unrelated defect instead: the
tier-pool cash split that tiers 2/3 size against has been `$0` on every tier, on both
accounts, since the pool-scoping code shipped. This doc supersedes that one's "wait" framing.

Authorities (read in this order):
- Prior handoff (still the audit-item ledger): `docs/superpowers/graywind-real-capital-audit-execution-handoff.md`
- Tier design (why pools exist, what they were supposed to do):
  `docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md`
- The claim being tested: `docs/superpowers/graywind-edge-thesis.md`
- No plan/spec exists for fixing this — it's a bug, not a feature. Nothing was implemented
  this session; this is a finding + recommendation only.

## How to resume (do this first)

1. Confirm where `main` actually is: `git log --oneline -5`. This session made **zero
   commits** — investigation only. The live cron still commits to `main` every cycle.
2. Verify the finding still holds (it may have been fixed or the pools funded since):
   `git show origin/main:state/tier_pools.csv` and `git show origin/main:state/small/tier_pools.csv`
   — if either shows non-zero `cash` for tier 2 or 3, this doc is stale, skip to owner notes.
3. Read "What has changed" below for the exact evidence chain before deciding what to do.
4. **Immediate next action:** this is an owner decision (how to fund the pools), not a
   coding task. See "What's next."

## Current state (active files)

**Branch:** `main`, in sync with `origin/main`. No local changes from this session.

**Files touched:** none. Read-only investigation via `git show origin/main:<path>` and
`git log --all -- <path>`.

**Files any fix will touch:**
- `state/tier_pools.csv`, `state/small/tier_pools.csv` — the two files that need seeding.
  No code writes non-zero values here; it is only ever hand-edited (see design spec line
  59-60, 146) or drained/credited by trades once seeded.
- Possibly `graywind_strategy/tier_config.py` (`TIER_TARGET_WEIGHTS`) if the fix is to add
  an automated seeding/validation step rather than a one-time manual edit.

**Scratch workspace / traps (carried forward, still true):**
- ⚠️ **Local checkout goes stale within hours** — always read live state via
  `git show origin/main:<path>`, never the working copy.
- ⚠️ **Two alarm labels** exist (`pipeline-alarm`, `macro-alarm`) — checked both this
  session via the public (unauthenticated) GitHub API, zero open issues on either. Note:
  unauthenticated, so a private-repo issue wouldn't show — this repo appears public, so the
  check is probably complete, but say which check you ran if you re-verify.
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` still has an
  uncommitted working-tree diff inherited from a prior session. Left as found, not this
  session's concern.
- ⚠️ Two other git worktrees still exist (`.claude/worktrees/...`). Leave alone.

**Not mine — leave alone:** everything the prior handoff already flagged
(`scripts/fetch_serv_bars.py`, `.claude/`, archived handoffs, `.venv/`, `__pycache__/`, etc).

## What has changed

Nothing shipped. This session re-verified two items from the prior handoff and found one
new defect:

1. **UNVERIFIED caveat from the prior handoff — resolved by inspection, not by waiting.**
   `save_equity_history()` (`live_loop.py:566`) sits in the same `finally` block as
   `append_decision_log`/`save_tier_pools`, which are proven to land on `origin/main` every
   cycle (visible commit history). It's called unconditionally with whatever the rolling
   breakers hold (tested with an empty list in `test_state_store.py`), and `state/` is not
   gitignored. `equity_history.csv` will appear on the next market-hours cycle; no separate
   wait-and-check is needed. (The 23:17Z 2026-08-31 run that predates this reasoning ran
   commit `9e4f2f2`, before the rolling breaker shipped in `1822d59` — it proves nothing
   either way and should be disregarded.)
2. **Macro-gate health checked locally against live data:**
   `GRAYWIND_STATE_DIR=<scratch> .venv/bin/python scripts/check_macro_health.py` against
   `origin/main:state/decision_log.csv` → `healthy (unavailable streak 0/8 cycles)`.
3. **NEW FINDING — tier pools have been `$0` since creation, on both accounts, verified
   across their entire git history:**
   - `git log --all -- state/tier_pools.csv` → **one commit ever**, `91bac2e`
     (2026-08-26T13:56Z). Every version of that file, checked directly, is
     `1,0.0 / 2,0.0 / 3,0.0`. Same for `state/small/tier_pools.csv`, first appearing even
     later (`0a391b7`, 2026-08-31T17:50Z), also always zero.
   - The pool-scoping code (`1b546b3`, "scope tiers 2/3 sizing and cash settlement to their
     own pool") landed 2026-08-25. **No commit, script, or doc ever seeded these files
     with real starting cash.** The design spec (`...tier-allocation-design.md:146`) only
     documents re-splitting cash *added later* ("no automated re-split logic, manual edit
     to `tier_pools.csv` only") — it never states an initial-seed step, and none was done.
   - **Direct consequence, confirmed against the live decision log
     (`origin/main:state/decision_log.csv`):** every SERV (tier 3) evaluation on the main
     account that gets a buy signal is blocked with `reason=position size rounds to zero
     shares` (e.g. three consecutive cycles on 2026-08-31, 13:26–13:49). This is exactly
     what `shares_to_buy()` does (`position_sizing.py:41-57`) when `account_equity==0`:
     `dollars_at_risk = 0 → shares = 0`. `sizing_equity` for tier 3 on main is
     `tier_pools[3] (0.0) + committed (0.0, no open SERV position)` = `0.0`. Confirmed, not
     inferred.
   - **Tier 2 (AAPL) on main is not dead, but its sizing is now decoupled from its mandate.**
     `sizing_equity = tier_pools[2] (0.0) + committed (open AAPL position: 160 sh ×
     $311.76 entry = $49,881.60)` ≈ **$49,882**, against main's actual 20%-of-equity tier-2
     mandate of `0.20 × $100,642.67 ≈ $20,129` — **running at ~2.5x its intended
     allocation**, purely because the pool component is zero and the position happens to
     be large. If that AAPL position is ever fully exited, tier 2 collapses to the same
     `$0` dead state as tier 3, with no warning.
   - **The small paper account is dead on both tiers.** `tier_pools` = `0.0/0.0/0.0` and
     zero open positions (`positions.csv` is empty) → `sizing_equity = 0` for both AAPL and
     SERV. This is a more precise explanation for the prior handoff's finding #3 ("small
     account... zero trades in two weeks") than its own guess ("possibly sub-MIN_NOTIONAL
     sizing flooring to zero shares") — it isn't a sizing-floor edge case, it's total
     starvation from an unseeded pool, present since the file was first created.
   - **`TIER_TARGET_WEIGHTS = {1: 0.70, 2: 0.20, 3: 0.10}` has zero code consumers**
     anywhere in the repo (only tier 1's *symbol* weights, `TIER1_SYMBOL_WEIGHTS`, are read,
     by `run_tier1_rebalance`). Nothing computes, enforces, or rebalances the 70/20/10 split
     between tiers — it exists only as a comment-documented intent.
   - Test suite still green throughout (`.venv/bin/python -m pytest -q` → 422 passed);
     this is a deployment/ops gap, not a code-logic bug the tests would catch — nothing in
     `tests/` asserts `tier_pools.csv` is ever non-zero at deploy time.

## What has failed / risks / caveats

- **This is not a code bug in the sense of wrong logic.** The pool-scoped sizing code does
  exactly what it's told; it was told the pools hold $0. It's a deployment step that was
  designed (implicitly) but never performed, and nothing detected the omission.
- **Reframe: "wait for burn-in" (the prior handoff's stated next action) is wrong as
  written.** Burn-in trade count was 6/20 as of this session
  (`git show origin/main:dashboard-data/trade_log.csv | tail -n +2 | wc -l`), and it
  **cannot advance** on the small account (fully starved) or meaningfully on tier 3 of the
  main account (fully starved) by just waiting — there is no cycle in which either pool
  will spontaneously acquire cash.
- **No alarm exists for this**, unlike the `macro-alarm` shipped last session. A `$0`
  tier pool degrades silently to `hold`/`no shares` decisions that look identical to "no
  qualifying signal today" in the dashboard.
- **UNVERIFIED / not yet decided:** whether the fix should be (a) a one-time manual edit to
  both `tier_pools.csv` files splitting current equity 70/20/10 (matches the spec's stated
  design — "manual edit... only"), or (b) a small script/check that seeds and validates
  pools are non-zero at first run, closer to how `check_macro_health.py` was added for the
  macro gate. Not decided or built this session — deliberately left for the owner (see
  advisor guidance below, which this handoff follows).
- **Do not seed `tier_pools.csv` without an owner decision.** For the main account, seeding
  properly would require re-deriving tier 2/3 pool cash net of the already-committed AAPL
  position (real money, real trade implications). For the small account, seeding is coupled
  to the still-pending **$500 re-fund** from the prior handoff — seeding at the current
  $2,000 basis would immediately need to be redone.
- Everything else in the prior handoff's caveats (provisional 5%/10% rolling-breaker
  thresholds, non-latching/permissive breaker design, `validate_symbol_addition()` having
  no caller, `delegate` unusable) is unchanged and still applies.

## What's next (ordered)

1. **Owner decision (not code): how to fund the tier pools.** Two options surfaced this
   session:
   - One-time manual edit to `state/tier_pools.csv` and `state/small/tier_pools.csv`,
     splitting each account's current total equity 70/20/10 per `TIER_TARGET_WEIGHTS`,
     netting out AAPL's already-committed value from main's tier-2 share. This matches the
     spec's documented (but never executed) design.
   - Write a small seeding/validation script (e.g. `scripts/seed_tier_pools.py`) that
     computes the split from live account equity and errors loudly (or raises a
     `pipeline-alarm`-style issue) if pools are ever `$0` with a non-empty `SYMBOL_TIER`,
     so this can't silently recur — the model to follow is `check_macro_health.py` /
     `71249c7`'s macro-alarm wiring.
2. **Once funded, re-verify against the live decision log**: SERV should stop returning
   `position size rounds to zero shares` on main, and the small account should start
   evaluating AAPL/SERV against non-zero `sizing_equity`.
3. **Then, and only then, resume the prior handoff's burn-in wait** — re-check
   `git show origin/main:dashboard-data/trade_log.csv | tail -n +2 | wc -l` against the
   20-trade floor. Funding the pools should make this counter actually move on both
   accounts, since tier 3 and the small account were previously structurally unable to
   contribute trades.
4. **Verify the rolling drawdown breaker / equity-history mechanism on the next trading
   day anyway** — inspection resolved *whether* it fires, but a real market-hours cycle
   confirming `state/equity_history.csv` actually lands on `origin/main` is still good
   practice (low priority, high confidence it's fine).
5. Everything else from the prior handoff's "What's next" (diversify the universe, set the
   Phase-3 advance bar, decide the news-debate gate's fate) is unchanged and still blocked
   behind burn-in — which is now blocked behind step 1 above.

## Verification idioms used in this project (for the resuming session)

- **Tests:** `.venv/bin/python -m pytest -q` from the repo root (`.venv`, not bare
  `python3`). 422 passing, unchanged this session.
- **Live state:** always `git show origin/main:<path>`, never the local checkout.
- **Tier pool history check** (the technique this session used to prove the gap):
  `git log --all -- state/tier_pools.csv` then `git show <each sha>:state/tier_pools.csv`
  — confirms a file's value across its *entire* history, not just its current tip.
- **Pipeline/macro health:** GitHub issues labelled `pipeline-alarm` and `macro-alarm`,
  checked via the public API when `gh` isn't installed locally:
  `curl -s "https://api.github.com/repos/<owner>/<repo>/issues?state=open&per_page=20"`.
- **Macro alarm, locally:** `GRAYWIND_STATE_DIR=<dir> .venv/bin/python
  scripts/check_macro_health.py`.
