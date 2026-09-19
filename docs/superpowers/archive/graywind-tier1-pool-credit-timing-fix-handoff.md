# Graywind Tier-1 Pool-Credit Timing Fix — Session Handoff

**Written:** 2026-09-03 · **For:** whoever resumes Graywind next — this session's fix is
SHIPPED and merged to `main`; the only open thread is a documented, currently-dormant design
gap that needs its own fix *before* tier 1 ever grows past one symbol.

## Goal

`run_tier1_rebalance()` (in `live_loop.py`) manages tier 1's monthly SPY buy-and-hold drift
rebalance. An earlier code review of the just-merged trade-approval-advisor feature (commit
`1798308`) flagged a real bug in it: sell orders credited `tier_pools[1]` (an internal cash
ledger) optimistically at submission time, before the fill was confirmed. Since a related
change now lets `run_tier1_rebalance` be re-invoked every ~15-minute cycle while a
same-rebalance buy proposal awaits owner approval, a lagging fill could double-count equity —
or, worse, a DAY sell order that never filled and got broker-cancelled would permanently
overstate the pool with nothing ever correcting it. This session fixed exactly that, via TDD,
then got it independently code-reviewed and committed.

- Commit: `3000363` — "Fix tier-1 rebalance pool-credit timing to defer until settlement observed"
- Prior commit that flagged the bug: `1798308` — "fix: address final-review findings on
  trade-approval-advisor"
- No spec/plan doc exists for this fix — it was small enough to go straight from the flagged
  review comment to TDD implementation to review to commit, in one session. This handoff *is*
  the record of it.
- Related, NOT this session's work — for broader project context if needed:
  `docs/superpowers/graywind-critical-review-handoff.md` (2026-09-01, a punch-list of unrelated
  priorities: diversify tactical universe, burn-in kill-check date, news-debate LLM funding
  decision, etc. — this session's fix was not on that list; it came from a code-review
  follow-up instead).

## How to resume (do this first)

1. Confirm base: `git log --oneline -3` on `main` should show `3000363` at or near the tip. If
   `main` has moved further, this fix is already in — just confirm it's still there
   (`git show --stat 3000363`) and read on for the open gap below.
2. Run `git status` — expect exactly the state described in "Current state" below. Anything
   beyond that is new since this handoff.
3. Run `.venv/bin/python -m pytest tests/ -q` — expect **481 passed, 0 failed**. (Two tests were
   failing earlier in this same session — `test_main_persists_todays_equity_into_the_rolling_history`
   and `test_main_survives_an_intraday_wipeout_without_abandoning_the_cycle` — confirmed
   pre-existing/unrelated, caused by the session crossing the ET-midnight boundary while the
   local machine's clock hadn't rolled over yet; reproduced identically with this diff stashed
   out. They now pass cleanly since the date rolled over, confirming that diagnosis.)
4. **Immediate next action:** nothing is blocking. This fix is done and shipped. The only
   carried-forward item is the dormant multi-symbol dedup gap in "What's next" below — it only
   needs action *when* someone proposes adding a second tier-1 symbol to `TIER1_SYMBOL_WEIGHTS`
   in `graywind_strategy/tier_config.py` (currently `{"SPY": 1.0}`), not before.

## Current state (active files)

**Branch:** `main`, at `3000363` (this session's commit sits directly on top of `1798308`).

**Files changed (committed in `3000363`):**
- `graywind_strategy/state_store.py` — new `load_tier1_holdings`/`save_tier1_holdings` +
  `TIER1_HOLDINGS_FILENAME`/`TIER1_HOLDINGS_FIELDS`, copied from the pre-existing
  `load_tier_pools`/`save_tier_pools` pattern.
- `live_loop.py` — `run_tier1_rebalance` gains `last_known_holdings=None`; a new loop (after
  fetching real `current_holdings`, before computing `tier1_equity`/orders) detects and credits
  *settled* decreases only; the old `tier_pools[1] += notional` at submission is removed;
  `main()` loads/threads/saves `last_known_tier1_holdings` alongside `tier_pools`/`pending_trades`.
- `tests/test_live_loop.py` — renamed/rewrote the sell test, added 4 new tests (credit-on-
  observed-decrease, no-credit-when-unchanged, no-phantom-credit-on-cold-start,
  defer-not-lose-credit-when-bars-unavailable-then-retry), plus a new autouse
  `isolate_tier1_holdings` fixture.
- `tests/test_state_store.py` — 4 new round-trip tests for the new load/save functions.

**Files NOT touched by this fix (context only):**
- `graywind_strategy/tier_config.py` — `TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}`, single-symbol
  today. This is the file that would need to change to trigger the dormant gap below.
- `graywind_strategy/tier1_rebalance.py` — the pure sizing logic (`compute_rebalance_orders`)
  this fix wraps; untouched, still correct as-is.

**Scratch workspace / traps:**
- ⚠️ `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` has an **uncommitted
  working-tree modification** (122 insertions / 213 deletions vs `HEAD`) that this session did
  not make and did not resolve — same file flagged as a trap in the 2026-09-01 critical-review
  handoff, still unresolved two sessions later. Do not trust the on-disk copy without
  `git diff HEAD -- docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` first.
- ⚠️ `docs/superpowers/graywind-critical-review-handoff.md` is untracked and still current for
  its own punch list (diversification, burn-in kill-check date, news-debate LLM funding) — that
  list is unrelated to and unaffected by this session's fix.

**Not mine — leave alone:**
- `.DS_Store`, `.claude/`, `docs/superpowers/archive/*`, `scripts/fetch_serv_bars.py` — untracked,
  pre-existing, not touched this session.

## What has changed

- `tier_pools[1]` is now credited for a sell only once a real holdings *decrease* is observed
  via a later cycle's fresh `trading_client.get_all_positions()` read, compared against a new
  persisted `last_known_tier1_holdings` baseline — never optimistically at submission.
- Verified correct by direct code reading (not just trusting tests) for: the exact
  submit→lag→observe→credit sequence: cold start (no phantom credit); an external/manual
  holdings *increase* (never misread as a decrease); multi-symbol independence in the credit
  loop itself (each symbol's decrease/no-change/increase handled independently in the same
  cycle).
- The missing-bars-defer edge case (caught by the implementer's own self-review mid-session,
  before this even reached code review) is correct: the baseline isn't advanced until a
  decrease can actually be priced, so it's retried indefinitely, never silently lost.
- Test suite: 481 passing, 0 failing as of this handoff (see step 3 above for the two flakes
  that resolved themselves once the ET-midnight boundary passed).

## What has failed / risks / caveats

- **Nothing has failed.** The fix is committed, reviewed, and all tests pass.
- **Decision carried forward, documented in the commit message and in `run_tier1_rebalance`'s
  own docstring — do not silently "fix" this without a deliberate design pass:** an independent
  code review found one **Important, currently-dormant** gap this fix does not close: nothing
  prevents resubmitting an identical sell order for a symbol whose prior sell hasn't settled
  yet. The *old* optimistic-credit code accidentally suppressed this side effect (crediting
  immediately shifted the computed drift back toward target on the very next cycle, so the same
  overweight signal wouldn't reappear); removing that optimistic credit for correctness also
  removed the side effect that was preventing duplicate resubmission.
  - **Why it's unreachable today:** `TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}` is single-symbol, and
    a single symbol at one target weight can only produce a buy *or* a sell per call, never
    both — so the specific trigger (a sell for symbol A submitted in the same cycle as an
    unresolved buy proposal for symbol B, which keeps `run_tier1_rebalance` being re-invoked
    every ~15 min while A's sell hasn't settled) cannot occur with only one symbol configured.
  - **When it becomes live:** the moment a second symbol is added to `TIER1_SYMBOL_WEIGHTS`.
    Buys already have a dedup guard (`if order.symbol in pending_trades: skip`, in
    `run_tier1_rebalance`) — sells have no equivalent. **Before adding a second tier-1 symbol,**
    add a matching dedup mechanism for in-flight sells (e.g., track "a sell for this symbol was
    already submitted and is awaiting settlement," persisted similarly to `pending_trades`, and
    skip generating a new sell for a symbol whose `last_known_holdings[symbol]` hasn't moved
    since one was last submitted this month).
- **Minor, non-blocking, noted in review but not acted on:** the credit's observation cadence
  can be as coarse as "next month" rather than "next 15-min cycle" for the current single-symbol
  config, because a sell-only rebalance (no buy orders) stamps `last_rebalance_month` on the
  same cycle it submits (only buy orders keep `should_rebalance_this_month` re-triggering), so
  `run_tier1_rebalance` — and the credit-observation check inside it — isn't called again until
  next month. Not a correctness bug (the credit is never lost, and the credit loop always runs
  before the equity/order computation within a call, so no phantom-buy misfire results), just a
  precision note: the eventual credit uses that later month's price, not a price close to the
  actual fill. No test exercises this specific interaction with the monthly gate.

## What's next (ordered)

1. **No immediate action required.** This fix is done, shipped, tested, and reviewed.
2. **Before anyone adds a second symbol to `TIER1_SYMBOL_WEIGHTS`** (`graywind_strategy/tier_config.py`):
   design and implement the sell-side dedup mechanism described above. Suggest starting with
   `superpowers:brainstorming` since it's a new design decision, not a bugfix — the shape of the
   right guard (a persisted "pending sell" set vs. reusing `last_known_holdings` staleness vs.
   something else) hasn't been decided yet.
3. **Separately, whenever convenient:** resolve the untracked working-tree modification to
   `docs/superpowers/graywind-news-debate-shadow-mode-handoff.md` (flagged as a trap in two
   consecutive handoffs now) — either commit it if intentional, or `git checkout` it back to
   `HEAD` if it's stray, after confirming with whoever last touched it.
4. **Unrelated but still open from the 2026-09-01 critical-review handoff** (not this session's
   scope, just still pending): diversify the tactical universe beyond AAPL/SERV, write a dated
   burn-in kill-check trigger, and decide on funding the news-debate LLM line item. See
   `docs/superpowers/graywind-critical-review-handoff.md` for the full ordered list.

## Verification idioms used in this project (for the resuming session)

- Test suite: `.venv/bin/python -m pytest tests/ -q` — 481 passing as of this handoff.
- To isolate this fix's own tests: `.venv/bin/python -m pytest tests/test_live_loop.py
  tests/test_state_store.py tests/test_tier1_rebalance.py -q`.
- To re-verify a suspected pre-existing/unrelated test failure isn't caused by your change:
  `git stash` the diff, re-run the suite, confirm the same failure reproduces, then `git stash
  pop`. This is how the two ET-midnight-boundary flakes were confirmed unrelated this session.
- To check whether a handoff/doc file is tracked before archiving or trusting it:
  `git ls-files --error-unmatch <path>` (exits non-zero if untracked).
