# Graywind Manual Trade Panel — Design Spec

**Written:** 2026-09-14 · Personal-use only, single owner. Builds on the existing
`live_loop.py` / `graywind_strategy/state_store.py` state model and the
`cron-trigger` Cloudflare Worker (`cron-trigger/src/index.js`), which already
dispatches `live-trading.yml` via `workflow_dispatch` behind a shared-secret
gate (`TRIGGER_SECRET`).

## Goal

Let the account owner click an open position on the dashboard (`index.html`)
and immediately place a real order against it — close it, sell part of it,
buy more, or attach a stop-loss/target — the way Fidelity, Robinhood, or
Alpaca's own UI lets you act on a position, instead of only watching the bot
manage it.

**Explicitly out of scope:**
- Leveraged/margin sizing ("2x–20x" as originally asked for). Alpaca equities
  accounts cap leverage at roughly 2x overnight / 4x intraday (PDT-gated);
  20x isn't offered for stocks on this broker. Dropped rather than scoped
  down to 2–4x, per the user's explicit call.
- Opening a brand-new position in a symbol not already on `WATCHLIST` /
  tracked in `open_positions`. This spec only acts on positions the bot
  already knows about.
- Limit orders on entry, trailing stops, or any order type beyond market
  (close/sell-partial/buy-more) and one GTC OCO bracket (stop/target).
- A second, private build of the dashboard. The public dashboard stays
  public; the action panel is gated by a token, not by hiding the page.

## Why this reopens a door the trade-approval-advisor spec closed

`docs/superpowers/specs/2026-08-26-graywind-trade-approval-advisor-design.md`
explicitly rejected a dashboard approve/reject button for new-position buys,
because the dashboard is static with no backend and building one was too
much new attack surface just to approve an entry a GitHub issue can already
gate with acceptable latency. That reasoning still holds for **entries** —
this spec doesn't touch `process_symbol`'s or `tier1_rebalance.py`'s proposal
flow at all, and new positions still open only via the GitHub-issue path.

What's different here: the user wants *instant* action on a position they
already hold, where GitHub-issue latency (minutes, needs a reaction on an
issue, resolved on the next 15-min cycle) defeats the point. That need
justifies building the authenticated write endpoint the advisor spec chose
to avoid — scoped narrowly (existing positions only, capped qty, breakers
still apply to the one risk-adding action) rather than opened generally.

## Components

### 1. Dashboard action panel (`index.html`)

Clicking a position row (`buildPositions`, `index.html:478`) opens a panel
instead of just displaying the row. The panel shows current shares/entry/
last price/unrealized P&L (data already in `statusRows`) and four actions:

- **Close position** — sells all held shares.
- **Sell partial** — qty input, capped client-side (and re-checked at the
  Worker) at the row's `shares`.
- **Buy more** — qty input.
- **Set stop/target** — one or both of a stop price and a target price.

A confirm step renders a plain-English summary ("Sell 10 shares of AAPL at
market (~$333.83)") before submit — no action fires on the first click.

The trade token is entered once and kept in `localStorage`
(`graywind_manual_trade_token`), never embedded in page source. Each submit
generates a client-side idempotency key (`crypto.randomUUID()`) sent with
the request, and the button disables until a response (success, rejection,
or timeout) comes back.

A small **recent actions** feed renders below Positions, sourced from a new
`dashboard-data/manual_actions.csv` (and the `small/` equivalent) — see
Component 4.

### 2. Cloudflare Worker (`manual-trade/`, sibling to `cron-trigger/`)

Same shape as `cron-trigger/src/index.js`'s manual-GET handler, extended to
accept a POST with a JSON body instead of only a GET with a query key:

- Rejects anything but `POST` with `Content-Type: application/json`.
- Rejects if the request's token doesn't match a Worker secret
  (`wrangler secret put MANUAL_TRADE_TOKEN`) — same fail-closed 404 pattern
  `cron-trigger` already uses for `TRIGGER_SECRET`, so a wrong token is
  indistinguishable from no route.
- CORS restricted to the dashboard's own origin (no `*`).
- Validates the payload shape: `{account, symbol, action, qty?, stop_price?,
  target_price?, idempotency_key}`. `account` must be one of the two known
  accounts; `symbol` must be a currently-open position for that account
  (looked up from that account's `dashboard-data/status.csv`, which the
  Worker can fetch from the repo's raw GitHub content — no separate state
  copy to keep in sync); `qty` for close/sell-partial/buy-more must be a
  positive integer, and for sell-partial/close must not exceed the
  position's current `shares`.
- On a valid request, calls `workflow_dispatch` on a new
  `manual-trade.yml` (mirroring `triggerGraywindCycle`), passing `account`,
  `symbol`, `action`, `qty`, `stop_price`, `target_price`, `idempotency_key`
  as workflow `inputs` (workflow_dispatch supports typed string inputs
  directly — no need for `repository_dispatch`'s client-payload shape).
- Returns 202 immediately on successful dispatch (this is fire-and-forget
  past this point — see "Error handling"), or the specific validation
  failure with 4xx.

### 3. GitHub Actions workflow + script

`manual-trade.yml` (`workflow_dispatch` with the inputs above) runs
`scripts/execute_manual_trade.py`, in the **same `concurrency` group** as
`live-trading.yml` (e.g. `group: graywind-live-state, cancel-in-progress:
false`) so a manual action and a scheduled cycle can never read/write
`state/` or `dashboard-data/` at the same time — they queue instead of
racing.

The script reuses `live_loop.py`'s Alpaca client construction and
`graywind_strategy/state_store.py` (`load_state`/`save_state`) for the
selected account's `GRAYWIND_STATE_DIR`.

**Idempotency:** before doing anything else, the script checks
`idempotency_key` against the last N rows of `manual_actions.csv`; if
already present, it no-ops and exits 0 (handles a double-click or a retried
dispatch).

**Pending-order conflict guard:** before any of the three sell-side actions
below submits a new order, the script checks
`position.get("pending_sell_order_id")`. If one is already set (an earlier
resting OCO, or a close/sell-partial still awaiting next-cycle settlement),
it cancels that order via Alpaca first, confirms the cancellation, and only
then submits the new one — so a position never carries two live sell-side
orders against the same shares at once.

**Per action:**

- **Close / Sell partial** — submits a `MarketOrderRequest` DAY sell for the
  requested qty (or full `shares` for close), then sets
  `position["pending_sell_order_id"]` and saves state via the existing
  `positions.csv` schema. No new settlement code: the next `live_loop.py`
  cycle's existing pending-sell-order machinery (`live_loop.py:348-430`)
  settles the real fill, credits `tier_pools`, and records the PDT day-trade
  exactly as it does for a stop/target exit today.
- **Buy more** — submits a `MarketOrderRequest` DAY buy, then synchronously
  updates `shares`/weighted-average `entry_price` and debits `tier_pools`,
  mirroring `process_pending_trades`'s existing approved-buy path
  (`live_loop.py:809-839`). Gated by the same checks that path already
  applies: drawdown breaker, rolling breakers, and tier-pool availability —
  this is the one action here that adds risk, so it stays behind the same
  gate automated buys use.
- **Set stop/target** — submits one Alpaca **OCO (one-cancels-other)
  bracket order**, GTC, with the given stop-loss and/or take-profit legs.
  Stores the resulting single order id as `position["pending_sell_order_id"]`
  and clears the position's plain `stop`/`target` fields (so
  `live_loop.py:417-424`'s own software-side check never fires a second,
  conflicting sell against the same shares). From this point the resting
  order is entirely owned by the existing pending-order settlement path —
  it can fill hours or days later, with no script running, and still gets
  picked up, credited, and recorded correctly on the next cycle that runs
  after the fill.
- Every branch appends one row to `manual_actions.csv` (`timestamp, account,
  symbol, action, qty, status, reason, idempotency_key`) and commits the
  updated `dashboard-data/` immediately — the action shows up on the
  dashboard within the workflow's own dispatch lag (roughly 10-60s), not on
  the next 15-minute cron tick.

### 4. `manual_actions.csv` + dashboard feed

New per-account file, append-forever like `trade_log.csv`. `buildPositions`
gains a sibling render function for a short "Recent actions" list (last ~10
rows) so a rejection (market closed, Alpaca error, breaker block) is visible
on the dashboard instead of silently vanishing after a fire-and-forget
dispatch.

## Data flow

Click position → panel shows live row data + action choice → confirm step
(plain-English summary) → submit with token + idempotency key → Worker
validates (qty vs. held shares, token, account/symbol shape) → 202 + workflow
dispatch → GitHub Actions run (queued behind `live-trading.yml` via the
shared concurrency group if one is mid-cycle) → script executes against
Alpaca, updates `state/` and `dashboard-data/`, appends to
`manual_actions.csv`, commits → dashboard reflects the new position state and
the action's outcome on next load.

## Safety

- **Buy more** is gated by drawdown breaker, rolling breakers, and tier-pool
  availability — same as an automated buy.
- **Close, sell-partial, and set-stop/target** are never blocked by
  breakers — matches the existing convention that breakers gate
  `can_open_new_trade()`, not exits or risk caps.
- Worker rejects a sell/close qty greater than the position's actual current
  `shares` before dispatching (fetched from that account's `status.csv`).
- Idempotency key (generated client-side, checked against
  `manual_actions.csv`) prevents a double-submit or a retried dispatch from
  firing the same order twice.
- Token lives only in the browser's `localStorage` and the Worker's secret
  binding — never in the page's HTML/JS source, never logged.
- CORS on the Worker restricted to the dashboard's own origin.

## Error handling

- **Pre-dispatch** (bad token, malformed request, qty exceeds held shares,
  unknown symbol/account): rejected synchronously by the Worker with a 4xx
  the panel shows inline, immediately.
- **Post-dispatch** (Alpaca rejects the order — market closed, insufficient
  buying power, breaker blocks a buy-more): recorded to
  `manual_actions.csv` with `status=rejected` and a reason; surfaced via the
  dashboard's "Recent actions" feed, visible within roughly a minute rather
  than silently dropped. The panel sets the user's expectation on submit
  ("Submitted — check Recent Actions in about a minute") rather than
  implying instant confirmation.

## Testing

- `scripts/execute_manual_trade.py`'s order construction, state updates, and
  idempotency check get unit tests with a mocked Alpaca trading client,
  following the existing test conventions in `tests/`.
- The Worker's validation logic (token check, qty-vs-held-shares, CORS) gets
  basic tests if `cron-trigger` already has a test setup to extend; otherwise
  a manual `curl` smoke test against a deployed dev Worker is acceptable for
  a project this size.
- Before calling this done: a real dry run during market hours against the
  **small account** first (close, sell-partial, buy-more, and a stop/target
  OCO), confirmed by reading back `positions.csv`, `tier_pools.csv`, and the
  dashboard — not against the main account until that's clean.
