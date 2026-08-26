# Graywind Trade-Approval Advisor — Design Spec

**Written:** 2026-08-26 · Personal-use only (confirmed with the user — this is not a
multi-user advisory product, no RIA/compliance surface). Builds on
`docs/superpowers/specs/2026-08-26-graywind-dual-account-tier-symbols-design.md` (both
accounts, `GRAYWIND_STATE_DIR`, `WATCHLIST = ["AAPL", "SERV"]`, tiers populated) — **should
ship after that work, not before**, since this spec's workflow changes assume the two-job
structure and per-account state directories that spec introduces.

## Goal

Turn Graywind from a fully autonomous trader into one where you approve every new position
before it opens, while keeping risk-management exits (stop-loss, target, tier-1 drift
rebalance) fully automatic — the bot proposes entries, you decide, it still protects capital
on its own.

**Explicitly out of scope:**
- Advising anyone other than the user — no multi-tenancy, no auth beyond "is this reaction
  from the repo owner," no compliance/disclaimer surface.
- Gating sells/exits — see "Why exits stay automatic" below.
- A dashboard approval UI — GitHub Issues is the entire approval surface (see "Why GitHub
  Issues" below).

## Why exits stay automatic

Gating a stop-loss or target exit behind human approval means a losing position keeps losing
while a proposal sits unanswered in a GitHub issue — the opposite of what a risk control is
for. Tier-1's monthly rebalance *can* also generate sell orders (trimming an overweight
position); those stay automatic too, same reasoning: a sell is capital protection or
mechanical rebalancing, not the kind of discretionary judgment call "advisor" is about. Only
new-position buys — including tier-1 rebalance buys, per the user's explicit choice to keep
"nothing buys without me" consistent across all three tiers — go through the gate.

## Why GitHub Issues, not a dashboard button or a CLI script

The dashboard (`index.html`) is static GitHub Pages with no backend — a real approve/reject
button would need a new authenticated write endpoint (serverless function or similar), new
infra and a new public attack surface for a personal project that doesn't need one. A local
CLI script needs zero new infra but requires the user to remember to run it; there's no
notification path. GitHub Issues sits in between: reuses infrastructure this repo already has
(the `pipeline-alarm` issue pattern, the same `GITHUB_TOKEN`/`issues: write` permission, the
same "workflow calls the GitHub API" shape) and — critically — the user already gets
notifications for new issues on repos they own, so a pending trade actually surfaces without
a new integration.

## Components

### 1. Proposal creation

Where `live_loop.py`'s `process_symbol` (tiers 2/3) or `tier1_rebalance.py`'s
`compute_rebalance_orders` (tier 1) would submit a **buy** order today, it instead calls a new
`trade_approval.propose_trade(...)` in `graywind_strategy/trade_approval.py`:

- Opens a GitHub issue via the REST API (plain `requests`, same no-SDK convention as
  `earnings_gate.py`'s Finnhub calls): title e.g. `"[Graywind $2k] Proposed BUY: SERV (tier 3)"`,
  body containing the reasoning (signal, price, quantity, tier, which gates passed), labels
  `pending-trade` + `account:small` or `account:100k` + `tier:N`.
- Appends a row to `state/pending_trades.csv` (respecting `GRAYWIND_STATE_DIR`, so it's
  automatically per-account): `issue_number, symbol, side, qty, price_at_proposal, tier,
  proposed_date`.
- **Before proposing:** check `pending_trades.csv` for an already-open proposal on that same
  symbol — if one exists, skip creating a duplicate issue this cycle (avoids spamming a new
  issue every 15 minutes while the existing one waits for a reaction).

### 2. Approval check (every cycle, before the entry-signal loop)

For every row in `pending_trades.csv`, `trade_approval.check_pending(...)`:

1. **Expired?** If `proposed_date != today`, close the issue with a comment
   ("expired — no decision by end of trading day"), remove the row, no order. (Matches tier
   2/3's short-timeframe RSI+MA signals — a morning proposal isn't a reliable read on
   afternoon conditions.)
2. **Reacted?** Fetch the issue's reactions via the GitHub API. **Only a 👍/👎 from the repo
   owner's GitHub username counts** — the repo is public, so this filter is a hard
   correctness requirement (a stranger's reaction on a public issue must never move real
   orders), not a style choice. Anyone else's reaction is ignored entirely.
   - 👎 → close with a comment, remove the row, no order.
   - 👍 → **re-validate before executing**, since time has passed since the proposal was
     created:
     - Current price within ~2% of `price_at_proposal` (a signal from three cycles ago at a
       very different price isn't the same trade anymore).
     - `drawdown_breaker.can_open_new_trade()` still true.
     - The symbol isn't already an open position (avoid double-buying if something else
       already opened it this cycle).
     - If all pass: submit the order via the existing `trading_client`/`PositionSizer` path
       exactly as an unapproved buy would today, close the issue with a confirmation comment,
       remove the row.
     - If any fail: close the issue with a comment explaining which check failed, remove the
       row, no order. (Fail closed — same convention as this project's existing gates.)
3. **No reaction yet, still today:** leave the issue open, leave the row in place, do nothing
   this cycle.

### 3. Workflow wiring

Both jobs in `live-trading.yml` (from the dual-account spec) need `GITHUB_TOKEN` in their
`env:` block — Actions already provides this as an implicit secret
(`${{ secrets.GITHUB_TOKEN }}`), it just isn't currently passed through to `live_loop.py`'s
process environment. `issues: write` permission is already declared workflow-wide (used today
by the `pipeline-alarm` steps), so no permissions change needed — reading reactions only needs
read access, which `issues: write` already implies.

### 4. Data flow summary

```
tier 2/3 signal fires (buy) ──┐
tier 1 rebalance wants to buy ─┼──► propose_trade() ──► GitHub issue + pending_trades.csv row
                                │
                                ▼
                    [next cycles: check_pending()]
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                 👍 (owner)  👎 (owner)   no reaction
                    │           │           │
              re-validate    close,      still today?
                 │  │        no order    │        │
            pass │  │ fail              yes       no (expired)
                 ▼  ▼                    │         │
             execute  close,          leave open  close,
             + close  no order         + row        no order
```

## Error handling

- GitHub API call failures (rate limit, transient network error) when creating or checking a
  proposal: caught and logged, same per-symbol try/except pattern `live_loop.py` already uses
  around each `WATCHLIST` symbol — one symbol's API hiccup must not block the rest of the
  cycle. A failed *check* just means the proposal is re-checked next cycle (nothing lost); a
  failed *creation* means the signal simply doesn't get proposed this cycle and can propose
  again next cycle if it still fires.
- A reaction from a non-owner account is not an error — it's silently ignored, logged at most
  as informational.
- If `pending_trades.csv`'s issue number is somehow already closed/deleted out-of-band (e.g.
  manually closed on GitHub without a reaction), `check_pending` treats a 404 from the issue
  API the same as "expired": remove the row, no order, don't crash the cycle.

## Testing

- `trade_approval.propose_trade`/`check_pending`: unit tests with mocked `requests` calls —
  duplicate-proposal suppression, expiry-by-date, owner-reaction filtering (a non-owner 👍
  must not trigger execution — this is the single most important test in this spec), the
  price-staleness re-check boundary (~2% pass/fail), each of the three re-validation checks
  failing independently.
- `live_loop.py`/`tier1_rebalance.py` integration: a buy signal creates a proposal instead of
  submitting an order directly (mocked `trading_client`, assert `submit_order` is NOT called
  on proposal creation, IS called only after a mocked owner 👍 passes re-validation) — same
  mocking style as `test_live_loop.py`'s existing `process_symbol` tests.
- Manual verification after deploy: trigger a real `workflow_dispatch` run during market
  hours with a symbol likely to signal, confirm the GitHub issue appears with correct
  reasoning, react 👍 as the repo owner, confirm the next scheduled cycle executes and closes
  it; separately confirm a 👍 from a different test account is ignored.

## Deferred, not forgotten

- Any UI beyond GitHub Issues (dashboard approval button, mobile push, etc.) — not needed for
  personal use, revisit only if the issue-based flow proves too slow/easy to miss in practice.
- Configurable expiry window (currently hardcoded to same-trading-day) — revisit if same-day
  turns out too tight or too loose after some real usage.
- Configurable price-staleness tolerance (currently ~2%) — same, revisit after real usage.
- Extending the approval gate to sells — deliberately rejected in this spec (see "Why exits
  stay automatic"); would need its own risk-analysis discussion if ever reconsidered, not a
  simple flag flip.
