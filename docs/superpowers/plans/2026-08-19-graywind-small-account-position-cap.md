# Graywind Small-Account Position-Value Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap a position's dollar value to a configured fraction of account equity, but only
below a configured equity threshold, so `PositionSizer.shares_to_buy` can't size a trade worth
more than the whole account on a low-equity account.

**Architecture:** Extend `PositionSizer` (`graywind_strategy/risk/position_sizing.py`) with two
new optional constructor params, `small_account_threshold` and `small_account_cap_fraction`.
`shares_to_buy` computes its existing risk-based share count exactly as before, then — only
when `account_equity` is below the threshold — also computes a value-based cap and takes the
minimum of the two. No new files; no changes to any other module, since `live_loop.py` and
`backtester.py` both construct `PositionSizer` with just `risk_fraction=0.01`, positional/
keyword-compatible with new params that carry defaults.

**Tech Stack:** Python, pytest.

## Global Constraints

- `small_account_threshold` default: `2000.0` — strict `<` comparison against `account_equity`
  (equity exactly at `$2,000` is NOT small-account mode).
- `small_account_cap_fraction` default: `0.50`.
- The cap only ever lowers `shares`, never raises it (implemented via `min(...)`, not
  reassignment).
- No changes to `pipeline.py`, `live_loop.py`, or `backtester.py` — they pick up the new
  defaults automatically through their existing `PositionSizer(risk_fraction=0.01)` calls.

---

### Task 1: Add small-account position-value cap to `PositionSizer`

**Files:**
- Modify: `graywind_strategy/risk/position_sizing.py:6-17` (the `PositionSizer` class)
- Test: `tests/test_position_sizing.py`

**Interfaces:**
- Consumes: nothing new — this task only touches the existing `PositionSizer` class.
- Produces: `PositionSizer(risk_fraction=0.01, small_account_threshold=2000.0,
  small_account_cap_fraction=0.50)` — both new params optional with those exact defaults.
  `shares_to_buy(account_equity, entry_price, stop_price)` keeps its existing signature and
  return type (`int`); its behavior changes only when `account_equity < small_account_threshold`.

- [ ] **Step 1: Write the first failing test — cap binds and lowers `shares`**

Add to `tests/test_position_sizing.py`:

```python
def test_shares_to_buy_caps_position_value_below_small_account_threshold():
    sizer = PositionSizer(risk_fraction=0.01)
    # Risk-based sizing alone would buy 200 shares ($1,000 = 100% of equity).
    # Below the $2,000 threshold, the 50% cap should bring it down to 100 shares ($500).
    shares = sizer.shares_to_buy(account_equity=1000, entry_price=5, stop_price=4.95)
    assert shares == 100
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_position_sizing.py::test_shares_to_buy_caps_position_value_below_small_account_threshold -v`
Expected: FAIL — with the current implementation this returns `200`, not `100`
(`AssertionError: assert 200 == 100`), since no cap exists yet.

- [ ] **Step 3: Implement the constructor params and the cap logic**

Replace the `PositionSizer` class in `graywind_strategy/risk/position_sizing.py` with:

```python
"""Fixed-fractional position sizing: risk a fixed percentage of account
equity per trade, sized off the distance to the stop-loss. Below
small_account_threshold, also caps position value to a fraction of
equity, since risk-based sizing alone can exceed the whole account when
equity is small relative to share price.
"""


class PositionSizer:
    def __init__(self, risk_fraction=0.01, small_account_threshold=2000.0,
                 small_account_cap_fraction=0.50):
        if not 0 < risk_fraction < 1:
            raise ValueError("risk_fraction must be between 0 and 1")
        self.risk_fraction = risk_fraction
        self.small_account_threshold = small_account_threshold
        self.small_account_cap_fraction = small_account_cap_fraction

    def shares_to_buy(self, account_equity, entry_price, stop_price):
        if stop_price >= entry_price:
            raise ValueError("stop_price must be below entry_price for a long position")
        risk_per_share = entry_price - stop_price
        dollars_at_risk = account_equity * self.risk_fraction
        shares = int(dollars_at_risk // risk_per_share)
        if account_equity < self.small_account_threshold:
            cap_shares = int((account_equity * self.small_account_cap_fraction) // entry_price)
            shares = min(shares, cap_shares)
        return shares

    @staticmethod
    def stop_loss_price(entry_price, stop_pct):
        return round(entry_price * (1 - stop_pct), 2)

    @staticmethod
    def take_profit_price(entry_price, take_profit_pct):
        return round(entry_price * (1 + take_profit_pct), 2)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_position_sizing.py::test_shares_to_buy_caps_position_value_below_small_account_threshold -v`
Expected: PASS

- [ ] **Step 5: Add the remaining three coverage tests from the spec**

Add to `tests/test_position_sizing.py`:

```python
def test_shares_to_buy_leaves_risk_based_sizing_unchanged_when_under_cap():
    sizer = PositionSizer(risk_fraction=0.01)
    # Risk-based sizing alone buys 5 shares ($250 = 25% of equity) -- already
    # under the 50% cap ($500 / $50 = 10 shares), so the cap must not bind.
    shares = sizer.shares_to_buy(account_equity=1000, entry_price=50, stop_price=48)
    assert shares == 5


def test_shares_to_buy_cap_does_not_apply_exactly_at_threshold():
    sizer = PositionSizer(risk_fraction=0.01)
    # Equity exactly at the $2,000 threshold is NOT small-account mode (strict <).
    # Risk-based sizing alone buys 400 shares ($2,000 = 100% of equity); if the
    # cap wrongly applied here it would reduce this to 200 shares.
    shares = sizer.shares_to_buy(account_equity=2000, entry_price=5, stop_price=4.95)
    assert shares == 400


def test_shares_to_buy_unaffected_far_above_threshold():
    sizer = PositionSizer(risk_fraction=0.01)
    # Equity far above the $2,000 threshold never enters small-account mode,
    # regardless of what fraction of equity the resulting position is worth.
    shares = sizer.shares_to_buy(account_equity=50000, entry_price=100, stop_price=99)
    assert shares == 500
```

- [ ] **Step 6: Run the full test file to verify everything passes**

Run: `python3 -m pytest tests/test_position_sizing.py -v`
Expected: PASS — all 8 tests (4 pre-existing + 4 new) pass, `0 failed`.

- [ ] **Step 7: Run the full project test suite to confirm no regressions**

Run: `python3 -m pytest tests/ -q`
Expected: PASS — the run ends in `passed`, `0 failed`.

- [ ] **Step 8: Commit**

```bash
git add graywind_strategy/risk/position_sizing.py tests/test_position_sizing.py
git commit -m "$(cat <<'EOF'
feat: cap position value for small accounts in PositionSizer

Risk-based sizing alone has no ceiling tied to account equity, which
only bites at low equity (e.g. a $500 account can size a position
worth more than the whole account). Below a $2,000 threshold, also
cap position value to 50% of equity.
EOF
)"
```

## Self-Review Notes

- **Spec coverage:** Architecture section (constructor params) → Task 1 Step 3. Sizing math
  section (exact cap formula, strict `<` boundary, `min` not reassignment) → Task 1 Step 3.
  Testing section's four cases → Task 1 Steps 1 and 5, with each test's expected value
  independently computed and verified before writing this plan (not asserted from the spec's
  prose alone). "Known interaction" section (post-multiplier overshoot) is explicitly accepted
  as-is in the spec — no task needed. "Deferred, not forgotten" items are explicitly out of
  scope — no task needed.
- **Placeholder scan:** No TBD/TODO; every step has runnable code and an exact expected
  assertion or pytest output.
- **Type consistency:** `shares_to_buy` signature and return type (`int`) unchanged throughout;
  `PositionSizer(risk_fraction=0.01)` (no override) used consistently across all four new tests,
  matching how `live_loop.py`/`backtester.py`/existing tests already construct it.
