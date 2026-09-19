# Graywind Quality-Control Audit + Fixes — Session Handoff

**Written:** 2026-09-06 · **For:** whoever resumes Graywind next — this session ran a
full-codebase `/code-review high` pass over `graywind_strategy/`, fixed 8 of the 9
findings with real TDD (red-green) cycles, and built out a genuine settlement-tracking
feature for one of them. **Nothing from this session is committed yet.**

## Goal

An ad hoc code-quality audit, not a planned effort — there is no spec/plan doc for this
work. The user asked to "run quality control spec over graywind," which after
clarification meant: run `/code-review` at high effort against the whole
`graywind_strategy` codebase, then fix everything it found. There is no other authority
document; this handoff **is** the record of what was found and what was done about it.

## How to resume (do this first)

1. **Confirm base:** `git rev-parse --abbrev-ref HEAD` → `main`. `git log --oneline
   origin/main..HEAD` → empty (local `main` has NOT diverged from `origin/main` by commit —
   all of this session's work is **uncommitted** in the working tree).
2. Run `git status` — expect exactly the modified/untracked files listed below.
3. Read this handoff in full. There is no prior handoff or plan this one supersedes or
   continues.
4. **Immediate next action:** review the working-tree diff (`git diff -- live_loop.py
   graywind_strategy/`) and decide whether to commit. The user has not asked for a commit
   yet — do not commit without being asked.

## Current state (active files)

**Branch:** `main`, 0 commits ahead of `origin/main` — everything below is **uncommitted**.

**Modified this session (all still uncommitted):**
- `live_loop.py` — the bulk of the work. New-day equity-wipeout guard, re-polled
  same-cycle drawdown check, `state_dir`/`headlines` threaded into `decide_trade`, and a
  full deferred-settlement rewrite of the stop/target sell path in `process_symbol` (see
  "What has changed" below).
- `graywind_strategy/state_store.py` — hardened 4 loaders against corrupt files
  (load_state's positions, tier_pools, pending_trades, tier1_holdings), made all their
  writes atomic (temp file + `os.replace`), and added a 7th column
  (`pending_sell_order_id`) to `POSITIONS_FIELDS`.
- `graywind_strategy/pipeline.py` — `decide_trade`/`evaluate_analyst_consensus_multiplier`
  now take `state_dir` (fixes a shared-cache-file bug between the two dual-account
  processes) and `headlines` (lets a caller pass in already-fetched headlines).
- `graywind_strategy/gates/analyst_consensus.py` — `save_cached_multiplier` now prunes to
  one row per symbol instead of appending forever.
- `graywind_strategy/gates/news_debate.py` — `evaluate_shadow_debate` accepts `headlines`
  to avoid a duplicate News API fetch.
- `graywind_strategy/risk/drawdown_breaker.py` — added `DrawdownBreaker.trip()`.
- `graywind_strategy/risk/pdt_throttle.py` — corrected a stale docstring (no logic change).
- `tests/test_live_loop.py`, `tests/test_state_store.py`, `tests/test_pipeline.py`,
  `tests/test_analyst_consensus.py`, `tests/test_news_debate.py`,
  `tests/test_drawdown_breaker.py` — new/updated tests for every item above.

**Pre-existing untracked files, NOT touched this session, leave alone:**
- `docs/superpowers/graywind-cron-trigger-completion-handoff.md`,
  `docs/superpowers/graywind-external-cron-trigger-handoff.md` (superseded prior
  handoffs — the latter has just been archived, see below)
- `docs/superpowers/archive/*.md` (5 files, already archived from before this session)
- `docs/superpowers/plans/2026-09-03-graywind-external-cron-trigger.md`,
  `docs/superpowers/plans/2026-09-03-graywind-symbol-reference-table.md`
- `scripts/fetch_serv_bars.py`, `.claude/`, `.DS_Store`

**Scratch workspace / traps:**
- ⚠️ **Nothing is committed.** Don't assume `origin/main` or even local `main`'s last
  commit reflects any of this. `git status`/`git diff` are the only ground truth.
- ⚠️ The three Alpaca order-lifecycle facts this session's sell-settlement design depends
  on (see below) were confirmed via **Alpaca's public docs and community forum threads**,
  not by an actual live probe against this project's real paper-trading account. They are
  credible (specific, consistent, cited) but **not verified against this account's real
  behavior**. Treat the design as sound-on-paper until it's run through a real cycle.
- ⚠️ `positions.csv` now has a 7th column (`pending_sell_order_id`). Old 6-column files
  still load fine (`state_store.py`'s loader uses `row.get(...)`, not `row[...]`, for this
  column specifically) — don't "fix" that into direct indexing.

**Not mine — leave alone:** everything under `.claude/worktrees/`, `.venv/`, `state/`,
`dashboard-data/`, `alpaca_data/`.

## What has changed

Ran `/code-review high --path graywind_strategy` (as a background fork) and got 9
findings, ranked by severity. Fixed 7 of them immediately with straightforward TDD:

1. **New-day equity wipeout crash** (`live_loop.py`) — `main()` would crash every cycle
   for the rest of the day if the account's equity was ≤0 on the first cycle of a new
   day. Added `DrawdownBreaker.trip()` so it fails closed instead.
2. **State-loader corruption crashes** (`state_store.py`) — 4 of 5 state loaders had no
   protection against a truncated file (a killed cron mid-write); all 5 now degrade
   safely with a loud stderr warning, and all the writes are now atomic.
3. **Stale same-cycle drawdown check** (`live_loop.py`) — re-polls real account equity
   after a stop/target exit instead of reusing a snapshot from before this cycle's price
   fetches.
4. **Shared analyst-consensus cache across the two dual-account processes**
   (`pipeline.py`) — now respects each account's own `state_dir`.
5. **Stale docstring** (`pdt_throttle.py`) — corrected.
6. **Unbounded analyst-consensus cache growth** (`analyst_consensus.py`) — prunes to one
   row per symbol now.
7. **Duplicate News API fetch** (`news_debate.py` + `pipeline.py` + `live_loop.py`) —
   shadow-mode debate now reuses the sentiment gate's already-fetched headlines.

The remaining 2 findings were both about tier-2/3 orders crediting `tier_pools`
optimistically at submission time instead of waiting for a confirmed fill (mirroring a
bug tier-1 rebalance already had fixed via an "observed settlement" pattern). The user
picked **Option A: build it properly** for these.

**Finding #3 (sell side) — DONE, substantial rewrite:**

Before writing any code, confirmed three Alpaca order-lifecycle facts against Alpaca's
own docs + community forum threads (an `advisor()` call had correctly blocked doing this
without confirming them first — see prior turn in this conversation for the full
reasoning):
- Order rejection (e.g. insufficient qty) raises synchronously as an `APIError` from
  `submit_order()`, not discovered later via polling.
- Resubmitting a sell for a symbol that already has an open sell order gets **rejected**
  by Alpaca's own qty-availability check (403 "insufficient qty available"), not stacked
  into a double-sell. This one fact substantially de-risked the whole design.
- `alpaca-py`'s installed `Order` model exposes `id`, `status` (an `OrderStatus` enum),
  `filled_qty`, `filled_avg_price`, `filled_at` — confirmed via static inspection of the
  installed package (`python -c "from alpaca.trading.models import Order; ..."`), same
  technique `sentiment_gate.py`'s own header comment already used for a different
  `alpaca-py` question.

Implementation in `live_loop.py`'s `process_symbol`:
- A stop/target exit submits the sell and sets `position["pending_sell_order_id"]`
  instead of crediting `tier_pools`/deleting the position immediately.
- A later cycle resolves it via `trading_client.get_order_by_id(...)`:
  - `FILLED` → credit the pool with the **real** `filled_qty × filled_avg_price`, record
    the PDT day-trade against `order.filled_at`'s date (not the resolving cycle's
    `today`), delete the position.
  - `CANCELED`/`EXPIRED`/`REJECTED`/`DONE_FOR_DAY` (`TERMINAL_UNFILLED_ORDER_STATUSES` in
    `live_loop.py`) → credit any partial fill, shrink `position["shares"]` by that much,
    clear the marker so the next stop/target check can retry.
  - Anything else (still in flight) → wait, skip resubmission and skip a fresh entry.
  - `get_order_by_id` itself raising → clear the marker and fall through to retry, rather
    than wedging the position forever (an `advisor()` review caught this as a real
    blocker before the fix was considered done — the first version left this unguarded).
- `reconcile_positions()` (runs every cycle, before `process_symbol`) now exempts a
  position with `pending_sell_order_id` set from its "not found at broker → drop it"
  rule. Without this, the moment a sell actually filled, `reconcile_positions` would
  silently delete the position **before** the settlement-check code above ever ran,
  permanently skipping the pool credit and PDT recording. Caught by the same `advisor()`
  review pass — **this is the kind of interaction bug most likely to recur if the buy
  side (below) is built the same way without checking for an equivalent.**

**Three deliberate behavior changes**, each with existing tests updated and a comment
explaining why:
1. `tier_pools` credit moves from submission time to confirmed-fill time.
2. PDT day-trade recording moves from submission time to fill time, keyed on
   `order.filled_at`'s date, not the resolving cycle's `today`.
3. A just-**submitted** exit no longer allows same-cycle re-entry into the same symbol
   (open_positions is keyed by symbol; can't represent "old position pending exit" and
   "new position just opened" at once). A just-**confirmed-settled** one still does.

**Known, accepted gap** (documented in a code comment, not fixed): if a partial fill's
remainder also fills same-day on a later retry, PDT gets double-counted for what's
really one round trip. Bounded (at most one extra count) and fails closed
(over-throttles, never under) — left as-is deliberately.

**Finding #4 (buy side) — NOT STARTED.** Same optimistic-credit bug, but on
`process_pending_trades`' approved-buy execution path. Scoped out of this session
deliberately (per `advisor()` guidance): unlike the sell side, submission and settlement
confirmation for an approved buy happen in **different cron invocations** of the same
kind the sell side already deals with, BUT there's no existing per-symbol "awaiting
settlement" tracking structure to hang it on — `pending_trades` is specifically for
awaiting-*approval* proposals, a different lifecycle stage. This needs:
- A new persisted state file (new `load_*`/`save_*` pair in `state_store.py`, its own
  tests) for "approved buy, order submitted, awaiting fill confirmation."
- A new per-cycle resolution function in `live_loop.py` (analogous to the sell-side logic
  now in `process_symbol`, but wired into `main()` similarly to how
  `process_pending_trades` is today).
- A rewrite of `process_pending_trades`' execution tail (currently: submit → immediately
  debit `tier_pools` and create `open_positions[symbol]`) and its existing tests.
- **Check for a `reconcile_positions()`-style gotcha on the buy side too** before
  considering it done — the sell side had one that wasn't obvious until an `advisor()`
  review caught it.

## What has failed / risks / caveats

- **Nothing has failed.** All 510 tests pass (`.venv/bin/python -m pytest tests/ -q`).
- **UNVERIFIED:** the sell-settlement design has never run against a real Alpaca paper
  cycle. The three facts it depends on are well-sourced but not confirmed in this
  project's actual account. Recommend a real dry run (or at minimum watching the next few
  live cycles' stderr output closely) before trusting it fully.
- **UNVERIFIED:** `TERMINAL_UNFILLED_ORDER_STATUSES` covers `CANCELED`, `EXPIRED`,
  `REJECTED`, `DONE_FOR_DAY` — the well-documented terminal-failure statuses. If a real
  cycle ever observes `REPLACED`, `STOPPED`, or `SUSPENDED` on a DAY market order, the
  position will sit in the "still in flight, wait" branch indefinitely for that status.
  Not expected for a plain DAY market sell, but not proven impossible either.
- This session's `advisor()` reviews caught two real bugs in the sell-settlement design
  before it was called done (the `reconcile_positions()` premature-drop interaction, and
  the unguarded `get_order_by_id` failure wedging a position forever). Both are now fixed
  and covered by tests, but they're evidence this kind of settlement-tracking feature has
  sharp edges — budget real review time for the buy-side equivalent, not just unit tests.

## What's next (ordered)

1. Decide whether to commit this session's changes (nothing is committed yet). If so,
   this is naturally two commits: the 7 mechanical quality fixes, and the sell-settlement
   feature — though the user may prefer one commit, ask if unclear.
2. Before or shortly after shipping, get a real paper-trading cycle to actually exercise
   the new settlement path (a stop/target exit really firing) and confirm the three
   Alpaca facts hold in practice, not just in docs.
3. Build finding #4 (buy-side settlement) as its own effort — see the design constraints
   above. Start with `superpowers:brainstorming` or `superpowers:writing-plans` given it's
   a genuine new feature, not a bug fix.
4. Not urgent, but worth a look: whether `TERMINAL_UNFILLED_ORDER_STATUSES` needs
   widening once real order statuses are observed in practice.

## Verification idioms used in this project (for the resuming session)

- Full suite: `.venv/bin/python -m pytest tests/ -q` from the repo root (uses the
  project's own `.venv`, not system Python). This session's baseline: **510 passed**.
- Targeted: `.venv/bin/python -m pytest tests/test_live_loop.py -k "<keyword>" -v` — the
  test files use descriptive `test_*` names, so `-k` on a keyword from the behavior you
  care about usually finds the right ones fast.
- This codebase's TDD convention (see any test file): a comment above each test states
  the failure scenario it exists to catch, often citing "final-review Fix N" or a
  specific prior bug — follow that convention for any new test.
