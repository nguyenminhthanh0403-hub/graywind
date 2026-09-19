# Graywind Punch-List Execution — Session Handoff

**Written:** 2026-09-15 · **For:** whoever picks up the user's punch list of Graywind fixes/features once the `feat/manual-trade-panel` branch's Task 5 is committed and out of the way. **Nothing in this effort has been implemented yet** — this handoff records live-verified findings and an advisor's ordering/grouping recommendation from this session's analysis, not a mid-implementation state.

## Goal

The user, after reviewing a status report of open Graywind objectives, gave a single combined instruction covering multiple items at once: fix the (then-newly-discovered) tier-pool funding bug, execute punch-list items 5 and 6, rule out sector-engine subsystems 2/3, execute the sector-engine roster flip, reanchor tier-1 rebalancing to true account equity, and explicitly skip the DeepSeek API key setup. This session investigated (did not yet implement) each piece, called in an advisor for scoping/ordering, and confirmed several facts live against `origin/main` and the real GitHub Actions/Bullion state before this handoff was written.

**No spec or plan file exists yet for this combined effort.** Given the number of interacting pieces (see "Grouping" below), consider `superpowers:writing-plans` before implementing rather than diving straight into code — several of these items share a single design decision and independent/parallel implementation would produce conflicting answers to it.

## How to resume (do this first)

1. **Confirm branch state first.** As of this writing, no new branch exists for this effort — the working tree was still on `feat/manual-trade-panel` (see that branch's own handoff, `docs/superpowers/graywind-manual-trade-panel-handoff.md`) with Task 5's uncommitted diff sitting on top. **Do not build this effort on top of that branch's uncommitted changes.** Check `git status`/`git branch -a` first; if Task 5 is now committed and that branch is merged/closed out, branch this effort off current `main`. If Task 5 is still open, ask the user which to prioritize before touching anything (this effort was explicitly queued to start only after Task 5).
2. **Re-verify every fact below against live state before trusting it** — `origin/main`'s `state/tier_pools.csv`, the Bullion `data.json` NFCI date, and the open GitHub issues may all have moved since 2026-09-15. Don't implement fixes against stale numbers.
3. Re-read the advisor's grouping/ordering guidance below in full before splitting this into parallel tasks — it specifically warns against per-item parallelism for the first three items.

## Live-verified facts as of 2026-09-15 (re-verify before trusting)

- **`state/tier_pools.csv` on the $100k ("100k") account is broken, contrary to what memory says was "SHIPPED and PUSHED" on 2026-09-01.** Confirmed via `git show origin/main:state/tier_pools.csv` (matches local checkout): `tier 1 = $0.0`, `tier 2 = $51,387.63`, `tier 3 = $0.0`. The small ($2k) account is correctly seeded (`$1,400 / $394.67 / $203.78` ≈ 70/20/10). `decision_log.csv` on the 100k account shows SERV (tier 3) repeatedly blocked with `"position size rounds to zero shares"` as recently as 2026-09-14T15:46. No `tier-pool-alarm` GitHub issue is open, because `scripts/seed_tier_pools.py`'s guard only fires when **all three** pools read exactly `$0` — tier 2 doesn't (it holds the AAPL position's committed value), so the 100k account's seeding silently never attempted, and never alarmed either since "never attempted" isn't the same failure shape as "attempted and failed."
- **Bullion's live cron is NOT dead** — `data.json` had a fresh row for 2026-09-15 (today, at time of writing) with real equity/index data. But the **NFCI field specifically** (one of `macro_gate.py`'s three vote inputs) last posted **2026-09-04** — 11 days stale against a 14-day weekly ceiling as of 2026-09-15, meaning as little as ~3 days of headroom left before `macro_gate` raises `MacroDataUnavailable` and **fails closed, silently blocking all new entries** on both accounts, indistinguishable from a real risk-off call.
- **The "real per-sector gate" and `macro_gate.py` are unrelated code paths** — the user's question conflated them. `graywind_strategy/gates/sector_gates.py` (currently just `energy_stub_gate`, always `True`) does NOT read Bullion at all. Only `macro_gate.py` does.
- **`DEEPSEEK_API_KEY` is not set** as a repo secret (confirmed via `gh secret list`) — per the user's explicit instruction this session ("don't worry about it"), leave it dormant. Not a punch-list item.
- **`WATCHLIST` in `live_loop.py` is still exactly `["AAPL", "SERV"]`** — the 6-symbol expanded roster (XOM/CVX energy, NVDA/MSFT tech, JNJ/UNH health) was backtested/validated in an earlier session but never flipped live. `SPY` is intentionally NOT in `WATCHLIST` — it's tier 1 at full weight via `TIER1_SYMBOL_WEIGHTS`, don't re-add it there.
- **Three GitHub trade-approval issues are/were live and in flight**: #13 (100k, AAPL), #14 (small, AAPL), #16 (small, SERV), all opened 2026-09-14, unresolved as of this writing. **These carry `tier` values and will resolve on the next live cycle** — changing `SYMBOL_TIER`/`WATCHLIST` while they're in flight risks the `tier=None` duplicate-order guard at `live_loop.py:~808` (see punch-list item 7 below). Either let them resolve first or explicitly re-verify safety with rows in flight before touching the roster.
- **Issue #8** (small account, AAPL, opened 2026-09-10) is an orphaned GitHub issue — still shows OPEN, but is no longer tracked in local `pending_trades.csv` (the bot already expired/dropped it internally; the best-effort `close_issue` call on expiry apparently failed silently, logged only to stderr). Inert (reacting to it triggers nothing), but should be manually closed as part of item 6 below.

## The advisor's grouping and ordering guidance (this session, not yet acted on)

> **Treat the tier-pool fix and tier-1 reanchoring as one change, not two.** Both answer the same question: what's the authoritative equity basis? Fix them independently and you double-count tier 1 — seeded pool cash *plus* a reanchored 70%-of-total-equity target.
>
> **Ordering, by what actually has a deadline:**
> 1. **NFCI staleness** — most time-sensitive. Check Bullion's FRED/NFCI fetch step specifically, not just that the daily cron runs generally.
> 2. Tier-pool + tier-1 reanchor, as one unit.
> 3. Item 6 (it covers the NFCI failure mode — see item 6 below).
> 4. Item 5.
> 5. Roster flip, last.
>
> **On the roster flip** — the sequencing decision on record is backtest-validate first (`scripts/validate_sector_engine.py`, `validate_symbol_addition`, `backtest_gate.py`), *then* touch `WATCHLIST`. Run them and report per-symbol results; a symbol that fails the DSR bar doesn't ship. Separately: the punch-list item-7 review found and reportedly fixed a **Critical `tier=None` duplicate-order loop described as "armed by the next watchlist expansion"** — this task IS that expansion. It's recorded as fixed at commit `1798308`; **re-verify it directly rather than trusting the note.** If any new symbol lands in tier 1, `TIER1_SYMBOL_WEIGHTS` gains a second entry and a parked mixed sell+buy rebalance retry gap becomes reachable — read the SDD ledger history at `1798308`'s parent chain first before doing that. Land outside market hours (the 15-min cron picks up `main` mid-day).
>
> **Item 5 — the boundary may be unreachable, which would itself be the finding.** `PositionSizer` receives *pool* equity, not account equity. Small-account pools are $1,400/$394/$204 — tier 2 sizes off $394, tier 3 off $204, nowhere near `small_account_threshold=2000.0`. Check the comparison operator (`<` vs `<=`, given the account sits at exactly $2,000.00) and what value `shares_to_buy` actually receives per tier. "The 50% cap is dead by construction under pool scoping" is a legitimate and more useful outcome than manufacturing a trade to trip it.
>
> **Item 6 — scope to the three silent failures already evidenced, don't build a framework:** (a) `close_issue` failing on expiry with stderr-only logging (issue #8 is live proof); (b) tier pools non-zero-but-wrong, which the current alarm misses since it only fires on "can't seed"; (c) unset secrets expanding to `""`. Close #8 as part of this.
>
> **Process:** grouping, not per-item parallelism. Items 1-3 above share an equity-basis decision — independent agents will make conflicting ones. Ruling out sector-engine subsystems 2/3 and the MAVIS redirect (see below) are memory edits, not code — do them last, they shouldn't consume plan slots.

## What's next (ordered — this is the advisor's ordering above, restated as a checklist)

1. **Check Bullion's NFCI fetch step** (separate small project, `~/Projects/bullion` or similar per memory — confirm actual path) — why is NFCI 11+ days stale when it's a real FRED series? Fix or confirm it's expected (FRED sometimes lags NFCI by design) before it trips the 14-day ceiling and silently halts Graywind.
2. **Design and implement ONE combined fix** for the tier-pool funding gap (100k account) and tier-1 reanchoring (`compute_rebalance_orders` currently uses `tier_pools[1] + committed` as its equity basis, which never re-checks against true total account equity) — pick a single authoritative equity-basis source used by both, per the advisor's warning against double-counting.
3. **Item 6**: close issue #8; add alarm coverage for (a) silent `close_issue` failures on expiry, (b) a tier pool that's non-zero but numerically wrong (not just "$0 and unseeded"), (c) an unset-secret-expands-to-empty-string failure mode — scoped narrowly, not a generic framework.
4. **Item 5**: investigate (not necessarily fix) whether the small-account 50%-position-cap is reachable at all under pool-scoped sizing. Report the finding even if the answer is "it's dead by construction, no code change needed."
5. **Sector-engine roster flip**: run `scripts/validate_sector_engine.py`/`backtest_gate.py` against the 6 expanded-roster symbols first, report per-symbol pass/fail, re-verify the `tier=None` guard from commit `1798308` actually holds, confirm no trade-approval issues are in flight, then flip `WATCHLIST` outside market hours.
6. **Memory/docs edits only, no code, do last:** mark sector-engine subsystems 2 (external financial data) and 3 (YouTube-transcript signal) as ruled out/won't-do; mark the performance-reports sub-project 3 ("personal advising UI") as redirected to the separate MAVIS effort rather than built inside Graywind.

## What has failed / risks / caveats

- **Nothing has been implemented in this effort yet** — everything above is investigation/verification only, done in the same session as the manual-trade-panel Task 5 work (see that handoff for the unrelated branch state to avoid confusing the two).
- **The tier-pool finding directly contradicts existing memory** (`project-graywind-tier-pool-funding-gap.md` says "SHIPPED and PUSHED 2026-09-01... 12 new tests, 434/434 suite passing"). That shipped fix genuinely works for a freshly-seeded account (proven by the small account) — it just doesn't handle the 100k account's specific starting condition (a pre-existing committed position making tier 2 non-zero while tiers 1/3 are zero). Don't assume the memory is simply wrong; the code does what it says, the edge case just wasn't covered.
- **All "live-verified facts" above have a timestamp of 2026-09-15 and will decay.** Especially the NFCI staleness (a moving deadline) and the three in-flight GitHub issues (#13/#14/#16 — likely resolved one way or another by the time this is read). Re-check before acting.

## Verification idioms used in this project (for the resuming session)

- `git show origin/main:state/tier_pools.csv` (and `state/small/tier_pools.csv`) — read the pushed state, not just a possibly-stale local checkout (though as of this session they matched).
- `gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state all` — check in-flight trade-approval proposals before touching tier/roster config.
- `gh secret list -R nguyenminhthanh0403-hub/graywind` — check which secrets actually exist rather than assuming.
- `curl -s "https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/data.json"` — Bullion's live public data feed; check the `history` dict's most recent date per field (`vix`, `nfci`, `hy_oas`, `us10y`, `us2y`), not just the top-level freshness, since fields can go stale independently.
- `.venv/bin/python -m pytest -q` — full suite, 571/571 passing as of this session (see the manual-trade-panel handoff for that number's context — it may change once that branch's Task 5 is committed).
