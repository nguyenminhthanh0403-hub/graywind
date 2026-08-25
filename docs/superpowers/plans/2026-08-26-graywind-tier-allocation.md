# Graywind Portfolio-Tier Allocation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the account's capital into three hard-partitioned pools (70/20/10) — tiers 2
and 3 reuse the existing intraday engine scoped to their own pool equity, tier 1 gets a new
buy-and-hold path with a monthly drift-triggered rebalance.

**Architecture:** A new static `tier_config.py` module (symbol→tier tagging + target weights),
two new small state files (`state/tier_pools.csv`, `state/tier1_rebalance.csv`) following
`state_store.py`'s existing round-trip pattern, a new pure-logic module
(`tier1_rebalance.py`) for the drift/sizing math, and targeted edits to `live_loop.py` that
are additive and no-op until `tier_config.py`'s dicts are actually populated (sub-project 2c,
separate work).

**Tech Stack:** Python 3.12/3.14, `pytest`, `unittest.mock` — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md`

## Global Constraints

- TDD (red/green) for every change to `gates/`/`pipeline.py`/`strategy_engine.py`/
  `backtester.py`/`risk/`/`live_loop.py` — this project's existing convention (per
  `docs/superpowers/graywind-phase1-mvp-handoff.md`).
- Run tests with the project's venv: `.venv/bin/python -m pytest tests/ -q` — plain `python3`
  lacks `yfinance` and other deps and fails to even collect several test files.
- `main()` itself is not unit-tested (real network/Alpaca calls) — this project's standing
  "integration validation via a real run" discipline. Task 4's `run_tier1_rebalance()` is
  extracted specifically so its logic *is* unit-testable; only the trigger wiring inside
  `main()` itself is left to manual/dry-run verification, matching how `process_symbol()`
  was already extracted from `main()` for the same reason.
- Reuse `graywind_strategy.risk.position_sizing.QTY_DECIMALS` for all fractional-quantity
  rounding in new code — do not redefine a second rounding constant.
- `SYMBOL_TIER` and `TIER1_SYMBOL_WEIGHTS` (Task 1) start **empty**. Every task below must
  keep the system fully functional with both empty (today's `WATCHLIST = ["AAPL", "SPY"]`
  behavior unchanged) — populating them is sub-project 2c, out of scope here.

---

## Task 1: Tier config module + tier-pool/rebalance-month state persistence

**Files:**
- Create: `graywind_strategy/tier_config.py`
- Modify: `graywind_strategy/state_store.py`
- Test: `tests/test_state_store.py`

**Interfaces:**
- Produces: `SYMBOL_TIER: dict[str, int]`, `TIER_TARGET_WEIGHTS: dict[int, float]`,
  `TIER1_SYMBOL_WEIGHTS: dict[str, float]` (all in `tier_config.py`); `load_tier_pools(state_dir=DEFAULT_STATE_DIR) -> dict[int, float]`,
  `save_tier_pools(tier_pools: dict[int, float], state_dir=DEFAULT_STATE_DIR) -> None`,
  `load_rebalance_state(state_dir=DEFAULT_STATE_DIR) -> dict` (with key `"last_rebalance_month"`),
  `save_rebalance_state(rebalance_state: dict, state_dir=DEFAULT_STATE_DIR) -> None` (all in
  `state_store.py`).

- [ ] **Step 1: Create `tier_config.py`**

```python
"""Static symbol-to-tier tagging for the 70/20/10 portfolio-tier split
(docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md).
Tier 1 = steady/safe/income (buy-and-hold, tier1_rebalance.py); tiers 2/3
= shorter-term/gamble, routed through the existing intraday engine
(decide_trade) scoped to their own pool equity.

Both dicts start empty -- populating them (sub-project 2c) is separate,
later work. Every consumer of these dicts must degrade gracefully to
today's behavior when they're empty (see live_loop.py's SYMBOL_TIER.get()
fallback and tier1_rebalance.run_tier1_rebalance()'s early return).
"""

SYMBOL_TIER = {}  # symbol -> 1 | 2 | 3

TIER_TARGET_WEIGHTS = {1: 0.70, 2: 0.20, 3: 0.10}  # fraction of total account capital

TIER1_SYMBOL_WEIGHTS = {}  # symbol -> target weight within tier 1 (should sum to 1.0 once populated)
```

- [ ] **Step 2: Write the failing tests for tier-pool state round-tripping**

Add to `tests/test_state_store.py` (new imports alongside the existing `load_state, save_state`
import at the top of the file):

```python
from graywind_strategy.state_store import (
    load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state,
)
```

```python
def test_load_tier_pools_returns_zero_defaults_when_no_file_exists(tmp_path):
    tier_pools = load_tier_pools(state_dir=str(tmp_path / "nonexistent"))
    assert tier_pools == {1: 0.0, 2: 0.0, 3: 0.0}


def test_save_then_load_round_trips_tier_pools(tmp_path):
    state_dir = str(tmp_path)
    save_tier_pools({1: 700.0, 2: 200.0, 3: 100.0}, state_dir=state_dir)
    tier_pools = load_tier_pools(state_dir=state_dir)
    assert tier_pools == {1: 700.0, 2: 200.0, 3: 100.0}


def test_load_rebalance_state_returns_none_when_no_file_exists(tmp_path):
    rebalance_state = load_rebalance_state(state_dir=str(tmp_path / "nonexistent"))
    assert rebalance_state == {"last_rebalance_month": None}


def test_save_then_load_round_trips_rebalance_state(tmp_path):
    state_dir = str(tmp_path)
    save_rebalance_state({"last_rebalance_month": "2026-08"}, state_dir=state_dir)
    rebalance_state = load_rebalance_state(state_dir=state_dir)
    assert rebalance_state == {"last_rebalance_month": "2026-08"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_state_store.py -q -k "tier_pools or rebalance_state"`
Expected: FAIL with `ImportError: cannot import name 'load_tier_pools'` (the functions don't
exist yet).

- [ ] **Step 4: Implement the state_store.py additions**

Add these constants near the existing `DEFAULT_STATE_DIR`/`OPERATIONAL_FIELDS` block at the
top of `graywind_strategy/state_store.py`:

```python
TIER_POOLS_FILENAME = "tier_pools.csv"
TIER_POOLS_FIELDS = ["tier", "cash"]
REBALANCE_FILENAME = "tier1_rebalance.csv"
REBALANCE_FIELDS = ["last_rebalance_month"]
```

Add these four functions at the end of `state_store.py`, after `save_state`:

```python
def load_tier_pools(state_dir=DEFAULT_STATE_DIR):
    tier_pools = {1: 0.0, 2: 0.0, 3: 0.0}
    path = os.path.join(state_dir, TIER_POOLS_FILENAME)
    if os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                tier_pools[int(row["tier"])] = float(row["cash"])
    return tier_pools


def save_tier_pools(tier_pools, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, TIER_POOLS_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TIER_POOLS_FIELDS, lineterminator="\n")
        writer.writeheader()
        for tier, cash in tier_pools.items():
            writer.writerow({"tier": tier, "cash": cash})


def load_rebalance_state(state_dir=DEFAULT_STATE_DIR):
    path = os.path.join(state_dir, REBALANCE_FILENAME)
    if os.path.exists(path):
        with open(path, newline="") as f:
            row = next(csv.DictReader(f), None)
        if row is not None:
            return {"last_rebalance_month": row["last_rebalance_month"] or None}
    return {"last_rebalance_month": None}


def save_rebalance_state(rebalance_state, state_dir=DEFAULT_STATE_DIR):
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, REBALANCE_FILENAME), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REBALANCE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({"last_rebalance_month": rebalance_state["last_rebalance_month"] or ""})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_state_store.py -q`
Expected: all pass (existing tests + 4 new ones).

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/tier_config.py graywind_strategy/state_store.py tests/test_state_store.py
git commit -m "feat: add tier config module and tier-pool/rebalance-month state persistence"
```

---

## Task 2: Tier-1 rebalance pure logic

**Files:**
- Create: `graywind_strategy/tier1_rebalance.py`
- Test: `tests/test_tier1_rebalance.py`

**Interfaces:**
- Consumes: `graywind_strategy.risk.position_sizing.QTY_DECIMALS` (existing, from
  sub-project 1).
- Produces: `RebalanceOrder` (dataclass: `symbol: str`, `side: str`, `qty: float`),
  `compute_rebalance_orders(tier1_equity: float, current_holdings: dict[str, float],
  current_prices: dict[str, float], target_weights: dict[str, float],
  drift_threshold: float = DRIFT_THRESHOLD) -> list[RebalanceOrder]`, `DRIFT_THRESHOLD = 0.05`,
  `should_rebalance_this_month(last_rebalance_month: str | None, today: date) -> bool` — pure
  trigger-condition helper, kept out of `main()` specifically so the monthly-trigger logic is
  unit-testable without violating this project's "don't unit-test `main()`'s real network
  calls" convention (see Global Constraints).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tier1_rebalance.py`:

```python
from datetime import date

from graywind_strategy.tier1_rebalance import (
    RebalanceOrder, compute_rebalance_orders, should_rebalance_this_month,
)


def test_no_order_when_within_drift_threshold():
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 6.0, "BND": 4.0},
        current_prices={"VTI": 100.0, "BND": 100.0},
        target_weights={"VTI": 0.6, "BND": 0.4},
    )
    assert orders == []


def test_sell_order_when_overweight():
    # target_value = 1000 * 0.6 = 600; current_value = 7.0 * 100 = 700;
    # drift = (700 - 600) / 1000 = 0.10 > 0.05 -> sell the gap: (700-600)/100 = 1.0 shares
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 7.0},
        current_prices={"VTI": 100.0},
        target_weights={"VTI": 0.6},
    )
    assert orders == [RebalanceOrder(symbol="VTI", side="sell", qty=1.0)]


def test_buy_order_when_underweight():
    # target_value = 600; current_value = 5.0 * 100 = 500;
    # drift = (500 - 600) / 1000 = -0.10 < -0.05 -> buy (600-500)/100 = 1.0 shares
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 5.0},
        current_prices={"VTI": 100.0},
        target_weights={"VTI": 0.6},
    )
    assert orders == [RebalanceOrder(symbol="VTI", side="buy", qty=1.0)]


def test_no_order_exactly_at_drift_threshold_boundary():
    # target_value = 600; current_value = 6.5 * 100 = 650;
    # drift = (650 - 600) / 1000 = 0.05 exactly -> NOT > threshold (strict), no order
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 6.5},
        current_prices={"VTI": 100.0},
        target_weights={"VTI": 0.6},
    )
    assert orders == []


def test_skips_symbol_missing_from_current_prices():
    # BND has no price -- must be skipped even though, if computed, its
    # drift (holds 0 against a 0.4 target weight) would clearly exceed
    # the threshold. VTI is exactly at target, so the empty result proves
    # BND was genuinely skipped, not coincidentally in-threshold too.
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 6.0, "BND": 0.0},
        current_prices={"VTI": 100.0},  # BND price missing
        target_weights={"VTI": 0.6, "BND": 0.4},
    )
    assert orders == []


def test_multiple_symbols_produce_independent_orders():
    orders = compute_rebalance_orders(
        tier1_equity=1000.0,
        current_holdings={"VTI": 7.0, "BND": 2.0},
        current_prices={"VTI": 100.0, "BND": 100.0},
        target_weights={"VTI": 0.6, "BND": 0.4},
    )
    assert orders == [
        RebalanceOrder(symbol="VTI", side="sell", qty=1.0),
        RebalanceOrder(symbol="BND", side="buy", qty=2.0),
    ]


# --- should_rebalance_this_month

def test_should_rebalance_when_never_rebalanced():
    assert should_rebalance_this_month(None, date(2026, 8, 26)) is True


def test_should_not_rebalance_when_already_done_this_month():
    assert should_rebalance_this_month("2026-08", date(2026, 8, 26)) is False


def test_should_rebalance_when_month_has_changed():
    assert should_rebalance_this_month("2026-07", date(2026, 8, 26)) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tier1_rebalance.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'graywind_strategy.tier1_rebalance'`.

- [ ] **Step 3: Implement `tier1_rebalance.py`**

```python
"""Pure sizing/drift logic for tier 1's monthly buy-and-hold rebalance --
no I/O, no Alpaca calls (docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md).
live_loop.py's run_tier1_rebalance() is the I/O wrapper that fetches
current holdings/prices and submits whatever orders this returns.
"""
from dataclasses import dataclass

from graywind_strategy.risk.position_sizing import QTY_DECIMALS

DRIFT_THRESHOLD = 0.05


@dataclass
class RebalanceOrder:
    symbol: str
    side: str  # "buy" | "sell"
    qty: float


def compute_rebalance_orders(tier1_equity, current_holdings, current_prices, target_weights,
                              drift_threshold=DRIFT_THRESHOLD):
    orders = []
    for symbol, weight in target_weights.items():
        if symbol not in current_prices:
            continue
        price = current_prices[symbol]
        target_value = tier1_equity * weight
        current_value = current_holdings.get(symbol, 0.0) * price
        drift = (current_value - target_value) / tier1_equity
        if drift > drift_threshold:
            qty = round((current_value - target_value) / price, QTY_DECIMALS)
            orders.append(RebalanceOrder(symbol=symbol, side="sell", qty=qty))
        elif drift < -drift_threshold:
            qty = round((target_value - current_value) / price, QTY_DECIMALS)
            orders.append(RebalanceOrder(symbol=symbol, side="buy", qty=qty))
    return orders


def should_rebalance_this_month(last_rebalance_month, today):
    return last_rebalance_month != today.strftime("%Y-%m")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tier1_rebalance.py -q`
Expected: all 9 pass.

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/tier1_rebalance.py tests/test_tier1_rebalance.py
git commit -m "feat: add tier-1 buy-and-hold rebalance pure logic"
```

---

## Task 3: `live_loop.py` — tier-scoped equity and cash settlement for tiers 2/3

**Files:**
- Modify: `live_loop.py:36` (imports), `live_loop.py:118-223` (`process_symbol`)
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `graywind_strategy.tier_config.SYMBOL_TIER` (Task 1).
- Produces: `process_symbol(..., tier_pools: dict[int, float] | None = None)` — new optional
  parameter. When the symbol is untagged in `SYMBOL_TIER`, or `tier_pools` is `None`,
  behavior is byte-for-byte identical to before this task (every existing caller/test needs
  no changes). When tagged AND `tier_pools` is provided: `decide_trade`'s `account_equity`
  becomes that tier's pool cash plus the cost basis of every other open position tagged to
  the same tier (mirrors `backtester.py`'s existing `committed_capital` pattern rather than
  fetching a fresh mark-to-market price); a buy/sell settles directly against
  `tier_pools[tier]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_live_loop.py`. First, extend the existing `_call` helper (near the top of
the file, right after the `_position` helper) to accept the two new parameters — this is a
test-infrastructure change, not a step of its own, since every existing call to `_call` must
keep working unchanged:

```python
def _call(symbol="AAPL", signal="hold", current_price=100.0, today=date(2024, 1, 8),
          open_positions=None, trading_client=None, pdt_throttle=None, decide_return=None,
          drawdown_breaker=None, equity=10000.0, tier_pools=None):
    open_positions = {} if open_positions is None else open_positions
    trading_client = MagicMock() if trading_client is None else trading_client
    pdt_throttle = MagicMock() if pdt_throttle is None else pdt_throttle
    drawdown_breaker = MagicMock() if drawdown_breaker is None else drawdown_breaker
    with patch(
        "live_loop.decide_trade",
        return_value=decide_return or TradeDecision(action="hold", reason="no buy signal"),
    ) as mock_decide:
        process_symbol(
            symbol=symbol, signal=signal, current_price=current_price, today=today,
            open_positions=open_positions, equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=MagicMock(),
            drawdown_breaker_ok=True, fred_api_key="k", news_client=object(),
            finnhub_api_key="k", trading_client=trading_client,
            drawdown_breaker=drawdown_breaker, tier_pools=tier_pools,
        )
    return mock_decide, trading_client, pdt_throttle, open_positions, drawdown_breaker
```

Then add these new tests, anywhere after the existing tier-agnostic ones:

```python
# --- tier-scoped equity/cash settlement (sub-project 2a/2b)

def test_process_symbol_uses_tier_equity_for_sizing_when_tagged():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 1}, clear=True):
        mock_decide, _, _, _, _ = _call(
            symbol="AAPL", signal="buy", equity=10000.0,
            tier_pools={1: 500.0, 2: 0.0, 3: 0.0},
        )
    assert mock_decide.call_args.kwargs["account_equity"] == 500.0


def test_process_symbol_falls_back_to_global_equity_when_untagged():
    with patch.dict("live_loop.SYMBOL_TIER", {}, clear=True):
        mock_decide, _, _, _, _ = _call(
            symbol="AAPL", signal="buy", equity=10000.0,
            tier_pools={1: 500.0, 2: 0.0, 3: 0.0},
        )
    assert mock_decide.call_args.kwargs["account_equity"] == 10000.0


def test_process_symbol_falls_back_to_global_equity_when_tier_pools_not_passed():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 1}, clear=True):
        mock_decide, _, _, _, _ = _call(symbol="AAPL", signal="buy", equity=10000.0)
    assert mock_decide.call_args.kwargs["account_equity"] == 10000.0


def test_process_symbol_buy_decrements_tier_pool_cash():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 1}, clear=True):
        tier_pools = {1: 500.0, 2: 0.0, 3: 0.0}
        _call(
            symbol="AAPL", signal="buy", current_price=100.0, equity=10000.0,
            tier_pools=tier_pools,
            decide_return=TradeDecision(
                action="buy", reason="all checks passed",
                shares=2.0, stop_price=95.0, target_price=110.0,
            ),
        )
    assert tier_pools[1] == 300.0  # 500.0 - 2.0 * 100.0


def test_process_symbol_stop_exit_increments_tier_pool_cash():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 1}, clear=True):
        open_positions = {"AAPL": _position(shares=2.0, stop=98.0, target=103.0)}
        tier_pools = {1: 500.0, 2: 0.0, 3: 0.0}
        _call(
            symbol="AAPL", current_price=97.0, open_positions=open_positions,
            tier_pools=tier_pools,
        )
    assert tier_pools[1] == 694.0  # 500.0 + 2.0 * 97.0


def test_process_symbol_tier_equity_includes_other_same_tier_positions():
    with patch.dict("live_loop.SYMBOL_TIER", {"AAPL": 1, "BND": 1}, clear=True):
        open_positions = {
            "BND": {"entry_price": 50.0, "shares": 4.0, "stop": 45.0, "target": 60.0, "opened_date": "2024-01-08"},
        }
        mock_decide, _, _, _, _ = _call(
            symbol="AAPL", signal="buy", open_positions=open_positions,
            tier_pools={1: 500.0, 2: 0.0, 3: 0.0},
        )
    assert mock_decide.call_args.kwargs["account_equity"] == 700.0  # 500.0 cash + 50.0*4.0 committed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -q -k tier`
Expected: FAIL — `TypeError: process_symbol() got an unexpected keyword argument 'tier_pools'`.

- [ ] **Step 3: Add the import**

In `live_loop.py`, add alongside the existing `graywind_strategy` imports (near line 36):

```python
from graywind_strategy.tier_config import SYMBOL_TIER
```

- [ ] **Step 4: Modify `process_symbol`'s signature**

Change (around line 118-122):

```python
def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None):
```

to:

```python
def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None, tier_pools=None):
```

- [ ] **Step 5: Compute `tier` at the top of the function body**

Right after the existing `if symbol_statuses is None: symbol_statuses = {}` block (before the
`position = open_positions.get(symbol)` line), add:

```python
    tier = SYMBOL_TIER.get(symbol)
```

- [ ] **Step 6: Settle a stop/target sell against the tier's cash**

Inside the `if position is not None and (...)` block, right after
`trading_client.submit_order(order)` (the sell order), add:

```python
        if tier is not None and tier_pools is not None:
            tier_pools[tier] += position["shares"] * current_price
```

- [ ] **Step 7: Compute tier-scoped sizing equity before the `decide_trade` call**

Change the `if position is None:` block's opening (before the `pending_today = sum(...)`
line) from nothing to:

```python
    if position is None:
        if tier is not None and tier_pools is not None:
            committed = sum(
                p["entry_price"] * p["shares"] for s, p in open_positions.items()
                if SYMBOL_TIER.get(s) == tier
            )
            sizing_equity = tier_pools[tier] + committed
        else:
            sizing_equity = equity
        pending_today = sum(
```

(the `pending_today = sum(` line and everything below it through the existing `decide_trade(`
call stays exactly as-is, except the one line changed in Step 8).

- [ ] **Step 8: Use `sizing_equity` in the `decide_trade` call**

Change `account_equity=equity,` (inside the `decide_trade(...)` call) to
`account_equity=sizing_equity,`.

- [ ] **Step 9: Settle a buy against the tier's cash**

Inside the `if decision.action == "buy":` block, right after
`trading_client.submit_order(order)` (the buy order), add:

```python
            if tier is not None and tier_pools is not None:
                tier_pools[tier] -= decision.shares * current_price
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -q`
Expected: all pass (existing tests unaffected + 6 new ones).

- [ ] **Step 11: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: scope tiers 2/3 sizing and cash settlement to their own pool"
```

**Correction found during the final whole-branch review:** this task, as originally written,
never included a step wiring `tier_pools=tier_pools` into `main()`'s real
`process_symbol(...)` call site (Steps 1-11 above only touch `process_symbol`'s own signature
and body). That gap meant `tier_pools` defaulted to `None` in production regardless of what
Task 3's tests proved about `process_symbol` in isolation, making all of this task's
tier-scoped sizing/settlement logic unreachable no matter how a later sub-project populated
`SYMBOL_TIER`. Fixed directly in the final-review fix wave (not re-run through Task 3's own
loop) by adding `tier_pools=tier_pools` to the `process_symbol(...)` call inside `main()`'s
`for symbol in WATCHLIST:` loop, plus a new `test_main_passes_loaded_tier_pools_to_process_symbol`
test in `tests/test_live_loop.py` pinning the wiring itself (mocking `process_symbol` and
asserting it's called with the exact object `load_tier_pools()` returned).

---

## Task 4: `live_loop.py` — tier-1 rebalance trigger and order placement

**Files:**
- Modify: `live_loop.py` (imports, new `run_tier1_rebalance` function, `main()`)
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `graywind_strategy.tier_config.TIER1_SYMBOL_WEIGHTS` (Task 1),
  `graywind_strategy.tier1_rebalance.compute_rebalance_orders` (Task 2),
  `graywind_strategy.state_store.{load_tier_pools, save_tier_pools, load_rebalance_state,
  save_rebalance_state}` (Task 1).
- Produces: `run_tier1_rebalance(trading_client, data_client, tier_pools) -> list[RebalanceOrder]`
  — fetches current tier-1 holdings/prices, computes orders via `compute_rebalance_orders`,
  submits them, and mutates `tier_pools[1]` in place to reflect the fills. Returns `[]`
  immediately (no I/O at all) when `TIER1_SYMBOL_WEIGHTS` is empty.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_live_loop.py`:

```python
from graywind_strategy.pipeline import TradeDecision  # already imported above; do not duplicate
import live_loop
from live_loop import run_tier1_rebalance  # add to the existing `from live_loop import ...` line
```

(Note: add `run_tier1_rebalance` to the existing `from live_loop import is_market_hours,
process_symbol` line at the top of the file rather than a second import line.)

```python
# --- run_tier1_rebalance (sub-project 2b)

def test_run_tier1_rebalance_returns_empty_when_no_tier1_symbols():
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {}, clear=True):
        orders = run_tier1_rebalance(MagicMock(), MagicMock(), {1: 700.0, 2: 0.0, 3: 0.0})
    assert orders == []


def test_run_tier1_rebalance_submits_orders_and_updates_tier_pool_cash():
    fake_bar = MagicMock(close=100.0)
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = [MagicMock(symbol="VTI", qty="5")]
    tier_pools = {1: 200.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 1.0}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[fake_bar]):
        orders = run_tier1_rebalance(trading_client, MagicMock(), tier_pools)
    # tier1_equity = 200.0 cash + 5.0 held * 100.0 price = 700.0
    # target_value = 700.0 * 1.0 = 700.0; current_value = 5.0 * 100.0 = 500.0
    # drift = (500.0 - 700.0) / 700.0 =~ -0.286 < -0.05 -> buy (700-500)/100 = 2.0 shares
    assert len(orders) == 1
    assert orders[0].symbol == "VTI"
    assert orders[0].side == "buy"
    assert orders[0].qty == 2.0
    trading_client.submit_order.assert_called_once()
    submitted = trading_client.submit_order.call_args[0][0]
    assert submitted.symbol == "VTI"
    assert submitted.side == OrderSide.BUY
    assert tier_pools[1] == 0.0  # 200.0 - 2.0 * 100.0


def test_run_tier1_rebalance_skips_symbol_with_no_recent_bars():
    trading_client = MagicMock()
    trading_client.get_all_positions.return_value = []
    tier_pools = {1: 700.0, 2: 0.0, 3: 0.0}
    with patch.dict("live_loop.TIER1_SYMBOL_WEIGHTS", {"VTI": 1.0}, clear=True), \
         patch("live_loop.fetch_bars", return_value=[]):
        orders = run_tier1_rebalance(trading_client, MagicMock(), tier_pools)
    assert orders == []
    trading_client.submit_order.assert_not_called()
    assert tier_pools[1] == 700.0  # untouched
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -q -k tier1_rebalance`
Expected: FAIL — `ImportError: cannot import name 'run_tier1_rebalance' from 'live_loop'`.

- [ ] **Step 3: Add the new imports**

In `live_loop.py`, extend the existing `from graywind_strategy.tier_config import
SYMBOL_TIER` line (added in Task 3) to also import `TIER1_SYMBOL_WEIGHTS`:

```python
from graywind_strategy.tier_config import SYMBOL_TIER, TIER1_SYMBOL_WEIGHTS
```

Add a new import for the rebalance logic:

```python
from graywind_strategy.tier1_rebalance import compute_rebalance_orders, should_rebalance_this_month
```

Change the existing `from graywind_strategy.state_store import load_state, save_state` line to:

```python
from graywind_strategy.state_store import (
    load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state,
)
```

- [ ] **Step 4: Implement `run_tier1_rebalance`**

Add this function above `main()`:

```python
def run_tier1_rebalance(trading_client, data_client, tier_pools):
    """I/O wrapper around tier1_rebalance.compute_rebalance_orders(): fetches
    each tier-1 symbol's latest bar and Alpaca's real current holdings,
    computes the rebalance orders, submits them, and updates tier_pools[1]
    in place to reflect the fills. No-ops entirely (zero I/O) when
    TIER1_SYMBOL_WEIGHTS is empty -- see tier_config.py.
    """
    if not TIER1_SYMBOL_WEIGHTS:
        return []

    now = datetime.now(ET)
    current_prices = {}
    for symbol in TIER1_SYMBOL_WEIGHTS:
        bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
        if bars:
            current_prices[symbol] = bars[-1].close

    real_positions = {p.symbol: float(p.qty) for p in trading_client.get_all_positions()}
    current_holdings = {symbol: real_positions.get(symbol, 0.0) for symbol in TIER1_SYMBOL_WEIGHTS}

    tier1_equity = tier_pools[1] + sum(
        current_holdings[s] * current_prices[s] for s in current_holdings if s in current_prices
    )
    orders = compute_rebalance_orders(
        tier1_equity=tier1_equity, current_holdings=current_holdings,
        current_prices=current_prices, target_weights=TIER1_SYMBOL_WEIGHTS,
    )
    for order in orders:
        market_order = MarketOrderRequest(
            symbol=order.symbol, qty=order.qty,
            side=OrderSide.BUY if order.side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(market_order)
        notional = order.qty * current_prices[order.symbol]
        tier_pools[1] += notional if order.side == "sell" else -notional
        print(f"{order.symbol}: submitted tier-1 rebalance {order.side} for {order.qty} shares")
    return orders
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -q -k tier1_rebalance`
Expected: all 3 pass.

- [ ] **Step 6: Wire the monthly trigger into `main()`**

In `main()`, right after `state = load_state()` (around line 247), add:

```python
    tier_pools = load_tier_pools()
    rebalance_state = load_rebalance_state()
```

Inside the `try:` block, right after `drawdown_breaker.update_equity(equity)` (around line 277)
and before `now = datetime.now(ET)`, add:

```python
        if should_rebalance_this_month(rebalance_state["last_rebalance_month"], today):
            try:
                run_tier1_rebalance(trading_client, data_client, tier_pools)
                rebalance_state["last_rebalance_month"] = today.strftime("%Y-%m")
            except Exception as exc:
                print(f"tier1 rebalance: error, will retry next cycle: {exc}", file=sys.stderr)
```

In the `finally:` block, right after the existing `save_state({...})` call, add:

```python
        save_tier_pools(tier_pools)
        save_rebalance_state(rebalance_state)
```

- [ ] **Step 7: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass, no regressions. This is `main()`'s only touch point in this task and it
is not unit-tested directly (per Global Constraints) — the next step is the manual
verification for that wiring.

- [ ] **Step 8: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: add tier-1 monthly rebalance trigger to the live loop"
```

- [ ] **Step 9: Manual verification (no code change)**

Both `SYMBOL_TIER` and `TIER1_SYMBOL_WEIGHTS` are still empty at this point (2c hasn't run),
so `run_tier1_rebalance` returns `[]` immediately every cycle and the rest of this task's
code is exercised but inert. Confirm this live, matching this project's existing "verify by
execution, not by reading" discipline: after pushing to `main`, check the next live cycle's
run log (`gh run view` or the GitHub Actions UI) for the line
`ERROR: one or more required API keys` (should NOT appear — unrelated regression check) and
confirm no new `tier1 rebalance: error` line appears in the log. `state/tier_pools.csv` and
`state/tier1_rebalance.csv` should appear in that cycle's commit, proving the new save calls
are wired in without needing 2c's symbol picks first. **Correction found during Task 4's
review:** `tier_pools.csv` will show `0.0` for all three tiers, but `tier1_rebalance.csv`
will NOT be empty — an empty `TIER1_SYMBOL_WEIGHTS` still makes `run_tier1_rebalance` *succeed*
(it returns `[]`, not an exception), so `last_rebalance_month` gets stamped with the real
current month on the very first cycle. Seeing that stamp is the success signal, not a bug —
an *empty* value there would actually mean the trigger never fired. (One real consequence,
harmless but worth knowing: if 2c populates `TIER1_SYMBOL_WEIGHTS` mid-month, the first real
rebalance is deferred to the following month, since the current month was already stamped by
this inert run.)
