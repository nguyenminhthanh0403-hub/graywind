# Graywind Portfolio-Tier Allocation — Design Spec

**Written:** 2026-08-26 · **Sub-project 2a+2b of 3** in the capital-scaling redesign that
started with [[project-graywind-capital-redesign]] (memory), whose sub-project 1
(tiered risk-fraction + fractional-share sizing) shipped 2026-08-25 (`13183cd`).

## Goal

Split the account's capital into three hard-partitioned pools with different risk postures:

- **Tier 1 (70%) — steady/safe/income.** Index funds and bonds, bought and held, rebalanced
  monthly against drift. No day-trading.
- **Tier 2 (20%) — shorter-term, predicted profitable.** Runs through the existing intraday
  RSI+MA engine (`decide_trade`, gates, stop/target exits), same as today's AAPL/SPY, just
  scoped to its own pool of capital and (eventually, sub-project 2c) its own symbol picks.
- **Tier 3 (10%) — deliberate gamble.** Same intraday engine as tier 2, smaller pool, riskier
  symbols (2c, not yet chosen).

At $1,000 starting capital (sub-project 1's still-pending manual step): $700 / $200 / $100.

**Explicitly out of scope for this spec:** which specific symbols go in which tier (2c —
separate, later spec). This spec is the plumbing that will hold whatever 2c picks.

## Why hard-partitioned pools, not target-weight rebalancing of the whole account

Alpaca has no native sub-accounts — one paper account, one equity number. A "70/20/10 of
total portfolio value, drift-rebalanced" model would need to compute each tier's current
weight from an interleaved set of positions and handle cross-tier drift, real complexity for
a $1,000 personal account. Three cash pools the bot tracks itself, where each tier's trades
only ever spend from and settle back into its own pool, is simpler, deterministic, and matches
how a retail investor already thinks about "three buckets." (User confirmed this trade-off
directly during brainstorming.)

## Components

### 1. Symbol → tier mapping

New module `graywind_strategy/tier_config.py`, same shape as `sector_config.py`'s
`SYMBOL_SECTOR`:

```python
SYMBOL_TIER = {
    # populated by sub-project 2c
}

TIER_TARGET_WEIGHTS = {1: 0.70, 2: 0.20, 3: 0.10}
```

**Rollout ordering:** `SYMBOL_TIER` starts empty — 2c (symbol research) is what populates
it, and hasn't happened yet. `live_loop.WATCHLIST` stays exactly as it is today
(`["AAPL", "SPY"]`) through this spec's implementation; a symbol not present in
`SYMBOL_TIER` falls back to today's account-wide-equity behavior unchanged (see Component 3).
This means 2a/2b can ship and run live immediately, with zero practical effect until 2c
actually adds entries — 2c's job becomes purely "add rows to `SYMBOL_TIER`" (and decide
whether/how to fold AAPL/SPY into a tier), no further plumbing changes needed.

### 2. Per-tier cash tracking

New state file `state/tier_pools.csv`: `tier,cash`. Loaded/saved via new functions in
`state_store.py` (`load_tier_pools`/`save_tier_pools`), following that module's existing
CSV round-trip pattern. Initialized once, manually, at setup time with each tier's starting
cash (`$700`/`$200`/`$100`) — there is no code path that (re)computes this split from a
total; adding capital later means manually deciding how the new money splits across tiers
and editing this file directly (matches sub-project 1's precedent of the Alpaca balance
change itself being a manual step, not automated).

A tier's **equity** (used for sizing and reporting, not stored) = its tracked cash + the
live mark-to-market value of every position tagged to that tier via `SYMBOL_TIER`.

### 3. Tiers 2 and 3 — reuse the existing intraday engine, pool-scoped

`live_loop.py`'s per-symbol processing looks up `SYMBOL_TIER.get(symbol)`. **If untagged
(`None`)** — true for every symbol until 2c runs — behavior is unchanged from today: full
account equity, no tier cash settlement. **If tagged**, it computes that tier's current
equity (cash + its positions' market value) and passes *that* — not the whole account's
Alpaca equity — as `account_equity` into `decide_trade`/`PositionSizer.shares_to_buy`. A
buy's cost decrements that tier's `cash` line; a sell's proceeds increment it. Since both
pools (~$200, ~$100) sit well under sub-project 1's $2,000/$5,000 thresholds, they
automatically get the low-capital risk-fraction (3%) and small-account value cap — no new
sizing logic needed here, tier 2/3 integration is entirely about which equity number gets
passed in and which cash line settles the trade.

No change to `decide_trade`'s gates, PDT throttle, or drawdown breaker — those stay
account-wide for now (a tier-scoped PDT/drawdown model is a real question but not one this
spec resolves; flagging as a known simplification, not a decision).

### 4. Tier 1 — new buy-and-hold + monthly rebalance path

**No `decide_trade`, no RSI signal, no stop/target, no PDT throttle** (a monthly rebalance
never same-day round-trips, so PDT doesn't apply). New module
`graywind_strategy/tier1_rebalance.py`:

- `compute_rebalance_orders(tier1_equity, current_holdings, current_prices, target_weights, drift_threshold=0.05) -> list[Order]`
  — pure function. For each symbol in `SYMBOL_TIER` tagged tier 1: `target_value =
  tier1_equity * target_weights[symbol]`, `current_value = current_holdings.get(symbol, 0) *
  current_prices[symbol]`, `drift = (current_value - target_value) / tier1_equity`. If
  `abs(drift) > drift_threshold`, emit a buy/sell order sized to close the full gap back to
  `target_value` (not just to the threshold edge), quantity = `abs(target_value -
  current_value) / current_prices[symbol]`, rounded to `QTY_DECIMALS` (reusing
  `position_sizing.QTY_DECIMALS` — no new constant). No stop/target computed; orders are
  plain `MarketOrderRequest`s, same DAY-order pattern already used everywhere else in
  `live_loop.py`.
- Trigger: a new state field (`state/tier1_rebalance.csv: last_rebalance_month`, e.g.
  `"2026-08"`). At the top of `live_loop.main()`, after the existing market-hours check:
  if `today.strftime("%Y-%m")` != the stored value, run the tier-1 rebalance once this
  cycle, then update the stored value. Every other cycle this month, tier 1 is skipped
  entirely — tiers 2/3 process every cycle as they do today, unaffected. This reuses the
  existing 15-min cron (no new GitHub Actions workflow) — user's explicit choice, trading
  a small monthly delay-window (first cycle of the month, whenever that lands relative to
  market open) for zero new CI surface.

## Error handling

- `compute_rebalance_orders` is pure (no I/O, no exceptions) — same testability precedent as
  `analyst_consensus_multiplier`/`macro_gate`'s pure-logic layer.
- The rebalance's own order-placement step (I/O) fails closed per this project's existing
  convention: an exception during tier-1 order submission must not crash the whole cycle or
  block tiers 2/3 — caught, logged, `last_rebalance_month` left unupdated so the next cycle
  retries rather than silently skipping a whole month.
- Missing/stale current-price data for a tier-1 symbol: skip that symbol's rebalance order
  this cycle (don't guess a stale price), same fail-safe spirit as the existing gates'
  fail-closed contracts, but scoped to that one symbol rather than blocking the whole
  rebalance.

## Testing

- `compute_rebalance_orders`: pure-function unit tests — no drift (no order), positive
  drift (sell order sized to close the gap), negative drift (buy order), drift exactly at
  the 5% boundary (no order, matching sub-project 1's small-account-cap precedent of
  strict `<` at boundaries), multiple symbols in one call.
- `live_loop.py` integration: month-change trigger fires the rebalance exactly once per
  calendar month regardless of how many cycles run that month; tiers 2/3 processing is
  unaffected on rebalance and non-rebalance cycles alike (mocked, same style as
  `test_live_loop.py`'s existing `process_symbol` tests).
- `state_store.py`: round-trip tests for `tier_pools.csv` and the new rebalance-month field,
  same pattern as existing `test_state_store.py`.

## Deferred, not forgotten

- Tier-scoped PDT/drawdown-breaker semantics (currently account-wide).
- What happens if a tier's pool cash goes to $0 or negative from losses — no explicit floor
  logic here; `PositionSizer`'s existing MIN_NOTIONAL floor will naturally stop tier 2/3 from
  buying, but tier 1's rebalance could still attempt a buy order that fails at the broker for
  insufficient tier-tracked cash (not caught locally). Worth a follow-up if it happens in
  practice.
- Adding capital later: no automated re-split logic, manual edit to `tier_pools.csv` only.
- Sub-project 2c (actual symbol picks per tier) — separate spec.
