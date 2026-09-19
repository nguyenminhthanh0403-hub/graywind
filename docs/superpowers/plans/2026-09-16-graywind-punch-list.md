# Graywind Punch-List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the funding gap that leaves the $100k account's tier 1 and tier 3 permanently unfunded, add the two narrowest silent-failure alarms the punch list evidenced, document (not necessarily fix) whether the small-account 50%-position-cap is reachable, and validate + flip the 6-symbol sector-engine roster if the backtest still clears the bar.

**Architecture:** `scripts/seed_tier_pools.py` gets a targeted fix: seed each currently-`$0` tier independently instead of requiring all three to read `$0` before it will act at all, and add a drift check so a tier that's non-zero-but-numerically-wrong also gets flagged. This alone makes `live_loop.py`'s existing `tier_pools[tier] + committed` equity basis correct going forward — no separate "reanchor" logic is added, which is deliberate: the advisor who scoped this work warned that fixing the funding gap and reanchoring independently would double-count tier 1's equity. `live_loop.py` gets one small addition (a `GITHUB_TOKEN` presence guard). Item 5 becomes a documentation task backed by a pinned regression test. The roster flip is validation-then-config, not new code, and is blocked on Alpaca credentials this session doesn't have — see Task 4.

**Tech Stack:** Python 3.14, pytest, existing `graywind_strategy` package, GitHub Actions (`live-trading.yml`).

**Spec:** No separate spec file — this plan's source is `docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md` (the 2026-09-15 investigation handoff) plus this session's own re-verification against live `origin/main` state and source (2026-09-16). Facts below were re-checked today; the handoff's are one day older.

## Global Constraints

- Every change must keep `.venv/bin/python -m pytest -q` at 571+/571 passing (root suite; `mavis/` is now excluded from root collection via `pytest.ini`, tested separately).
- `TIER_TARGET_WEIGHTS = {1: 0.70, 2: 0.20, 3: 0.10}` (`graywind_strategy/tier_config.py`) — do not change these values as part of this plan.
- Never overwrite a tier's accumulated ledger cash in `tier_pools.csv` unless that tier currently reads exactly `$0.0` — this is the existing, tested safety invariant in `scripts/seed_tier_pools.py` and must survive every task here.
- `DEEPSEEK_API_KEY` stays unset/dormant per the user's explicit 2026-09-15 instruction — out of scope for this plan.
- Land each task's commit outside market hours where it touches `live_loop.py` or `scripts/seed_tier_pools.py` (both run every ~15-30 min, 13:07-20:37 UTC weekdays, per `.github/workflows/live-trading.yml`'s cron) so a bad deploy doesn't get picked up mid-cycle before you can react.

## Re-verified facts (2026-09-16, supersede the 2026-09-15 handoff where they differ)

- **NFCI staleness is NOT currently a problem.** The 2026-09-15 handoff flagged it as ~3 days from tripping `macro_gate.py`'s 14-day ceiling. Checked directly against both FRED's raw `NFCI` series and Bullion's live `data.json` today: Bullion picked up FRED's 2026-09-11 value (confirmed via `curl https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/data.json`, `history["2026-09-11"]["nfci"]` present), which is 5 days old as of 2026-09-16 — well inside the 14-day ceiling. `macro_gate.py`'s `_most_recent_value_before()` (lines 67-81) correctly walks backward past the intervening days where the `nfci` key is absent entirely (confirmed live: 2026-09-12 through 2026-09-16 rows have no `nfci` key at all, not a `null` value — `if field not in record: continue` at line 73 handles this correctly). **No code change needed here.** This was the advisor's own caveat ("FRED sometimes lags NFCI by design") playing out normally, not a bug. Re-check this yourself if picking this plan up more than a few days after 2026-09-16 — NFCI publishes weekly and the gap will widen again until the next Friday-ish release.
- **The $100k account's tier-pool bug is confirmed still live** (`git show origin/main:state/tier_pools.csv` as of 2026-09-16: tier 1 = `$0.0`, tier 2 = `$51,387.63`, tier 3 = `$0.0`). Root cause confirmed by reading `scripts/seed_tier_pools.py` directly: `pools_are_unfunded()` (line 63-64) requires **every** tier to read exactly `$0.0` before it will seed anything; tier 2's committed AAPL position keeps it non-zero, so the whole script no-ops every cycle and tier 1/tier 3 never get funded. Task 1 below fixes this at the root.
- **Issue #8 is still open** (`gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open` as of 2026-09-16 shows #8, opened 2026-09-10, alongside two new legitimate proposals #18/#19 from today). Confirms the handoff's finding that `close_issue`'s expiry-path failure (`live_loop.py:829-836`, deliberately best-effort by design — see the comment there) can leave an orphaned open issue with nothing tracking it locally.
- **`GITHUB_TOKEN` is read without a not-empty guard** (`live_loop.py:968`, `github_token = os.environ.get("GITHUB_TOKEN")`), unlike the four keys already guarded at line 964 (`if not all([api_key, api_secret, fred_api_key, finnhub_api_key])`). A blank `GITHUB_TOKEN` would make every `trade_approval` GitHub API call fail, and those failures are swallowed by the per-symbol `except Exception` at `live_loop.py:934` (stderr-only) — this is a live, unguarded instance of the "unset secret expands to `""` and fails silently" failure mode named in punch-list item 6(c).
- **The 6-symbol roster expansion's backtest tooling already has all 6 symbols wired in** (`scripts/validate_sector_engine.py`'s `SYMBOLS` dict and `graywind_strategy/sector_config.py`'s `SYMBOL_SECTOR` both already list XOM/CVX/NVDA/MSFT/JNJ/UNH) — but the roster CSVs themselves (`data/roster/*.csv`) are gitignored and not present in this checkout, and this local shell has no `ALPACA_API_KEY` to refetch them. Task 4 documents the exact commands but cannot be executed from this session.

---

### Task 1: Seed each unfunded tier independently, not only when all three are `$0`

**Files:**
- Modify: `scripts/seed_tier_pools.py`
- Test: `tests/test_seed_tier_pools.py`

**Interfaces:**
- Produces: `zero_tiers(tier_pools: dict[int, float]) -> set[int]` — replaces `pools_are_unfunded`, which this task removes.
- Produces: `_committed_by_tier(market_value_by_symbol, symbol_tier, tier1_symbol_weights) -> dict[int, float]` — extracted so Task 2's drift check can reuse it without duplicating the committed-value logic.
- `compute_seed_split`'s signature and behavior are unchanged (still pure, still floors at 0) — only its internals are refactored to call `_committed_by_tier`.

- [ ] **Step 1: Write the failing test for partial-funding seeding**

Add to `tests/test_seed_tier_pools.py`, in the `# --- main() integration ---` section:

```python
def test_partially_funded_pool_seeds_only_the_zero_tiers(tmp_path, monkeypatch):
    """Reproduces the live $100k-account bug: tier 2 already holds a
    committed position (non-zero), tiers 1 and 3 are still $0. The old
    all-or-nothing pools_are_unfunded() skipped seeding entirely whenever
    any tier was non-zero -- this pins the fix."""
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 0.0, 2: 51_387.63, 3: 0.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2, "SERV": 3})
    monkeypatch.setattr(seed_tier_pools, "TIER1_SYMBOL_WEIGHTS", {"SPY": 1.0})
    monkeypatch.setattr(seed_tier_pools, "TIER_TARGET_WEIGHTS", {1: 0.70, 2: 0.20, 3: 0.10})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        mock_cls.return_value.get_account.return_value = _mock_account(250_000.0)
        mock_cls.return_value.get_all_positions.return_value = [
            _mock_position("AAPL", 51_387.63),
        ]
        assert main() == 0

    result = load_tier_pools(state_dir=state_dir)
    assert result[1] == pytest.approx(175_000.0)   # 70% of 250k, SPY has no position yet
    assert result[2] == pytest.approx(51_387.63)   # untouched -- was already funded
    assert result[3] == pytest.approx(25_000.0)    # 10% of 250k, SERV has no position yet
    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")
```

Also replace the two `pools_are_unfunded` unit tests with their `zero_tiers` equivalents:

```python
# --- zero_tiers ---

def test_all_zero_are_all_zero_tiers():
    assert zero_tiers({1: 0.0, 2: 0.0, 3: 0.0}) == {1, 2, 3}


def test_only_the_zero_tiers_are_returned():
    assert zero_tiers({1: 70_000.0, 2: 0.0, 3: 10_000.0}) == {2}


def test_no_zero_tiers_returns_empty_set():
    assert zero_tiers({1: 70_000.0, 2: 5_000.0, 3: 10_000.0}) == set()
```

And update the existing `test_main_skips_entirely_when_pools_already_funded` fixture — under the old semantics tier 2 = `0.0` was used to mean "funded" (any-nonzero), which no longer applies:

```python
def test_main_skips_seeding_when_pools_already_funded(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 70_000.0, 2: 5_000.0, 3: 10_000.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2})
    monkeypatch.setattr(seed_tier_pools, "TIER_TARGET_WEIGHTS", {1: 0.70, 2: 0.20, 3: 0.10})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        mock_cls.return_value.get_account.return_value = _mock_account(85_000.0)
        mock_cls.return_value.get_all_positions.return_value = [_mock_position("AAPL", 5_000.0)]
        assert main() == 0

    # no zero tiers, so nothing gets seeded -- but the client IS called now,
    # for Task 2's drift check
    assert load_tier_pools(state_dir=state_dir) == {1: 70_000.0, 2: 5_000.0, 3: 10_000.0}
    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")
```

(This replaces the old test's `mock_cls.assert_not_called()` assertion — Task 2 makes `main()` always fetch live account state when credentials are present, to run the drift check even when there's nothing to seed. Note this in the commit message.)

- [ ] **Step 2: Run the new/changed tests, confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_seed_tier_pools.py -v`
Expected: `test_partially_funded_pool_seeds_only_the_zero_tiers` FAILs (tier 1/3 stay `0.0` — `pools_are_unfunded` sees tier 2 non-zero and skips seeding entirely). `test_all_zero_are_all_zero_tiers` / `test_only_the_zero_tiers_are_returned` / `test_no_zero_tiers_returns_empty_set` FAIL with `NameError: name 'zero_tiers' is not defined`. `test_main_skips_seeding_when_pools_already_funded` FAILs on the `mock_cls` call not happening yet (that part lands in Task 2, so this specific test may still fail until Task 2 lands — that's expected; note it in the commit and move on if the seeding-only assertion already passes).

- [ ] **Step 3: Implement the fix**

Replace `scripts/seed_tier_pools.py` lines 41-64 (from `def compute_seed_split` through `def pools_are_unfunded`) with:

```python
def _committed_by_tier(market_value_by_symbol, symbol_tier, tier1_symbol_weights):
    """{tier: sum of open-position market value for symbols mapped to that
    tier}, via tier1_symbol_weights for tier 1 and symbol_tier for tiers 2/3.
    Shared by compute_seed_split (Task 1) and pools_drifted (Task 2) so the
    two never compute "what's already committed" two different ways.
    """
    committed = {}
    for symbol in tier1_symbol_weights:
        committed[1] = committed.get(1, 0.0) + market_value_by_symbol.get(symbol, 0.0)
    for symbol, tier in symbol_tier.items():
        committed[tier] = committed.get(tier, 0.0) + market_value_by_symbol.get(symbol, 0.0)
    return committed


def compute_seed_split(total_equity, market_value_by_symbol, target_weights=TIER_TARGET_WEIGHTS,
                        symbol_tier=None, tier1_symbol_weights=None):
    """Pure: {tier: cash_to_seed} from live account equity and each open
    position's market value. Floors at 0 -- a tier whose existing position
    already exceeds its target gets $0 seeded cash, never negative; this
    script does not sell anything to force a tier back to its mandate.
    """
    symbol_tier = symbol_tier if symbol_tier is not None else {}
    tier1_symbol_weights = tier1_symbol_weights if tier1_symbol_weights is not None else {}
    committed = _committed_by_tier(market_value_by_symbol, symbol_tier, tier1_symbol_weights)
    return {
        tier: max(0.0, total_equity * weight - committed.get(tier, 0.0))
        for tier, weight in target_weights.items()
    }


def zero_tiers(tier_pools):
    """The tiers currently reading exactly $0.0 -- these are the only ones
    eligible for seeding. Replaces the old all-or-nothing
    pools_are_unfunded(): a tier with a pre-existing committed position
    (e.g. tier 2 holding AAPL) can be genuinely funded while a sibling tier
    (tier 1, tier 3) never received its share, and the old all-tiers check
    skipped seeding entirely whenever any single tier was non-zero -- this
    is exactly the $100k account's live bug as of 2026-09-16.
    """
    return {tier for tier, cash in tier_pools.items() if cash == 0.0}
```

Then update the docstring at the top of the file (lines 17-22) — replace:

```
Idempotent by construction: only ever WRITES a fresh seed when every tier
currently reads exactly $0.0 (the actual unfunded state today). Once seeded,
at least one tier will almost certainly be non-zero (a real position's
market value essentially never lands on the exact target dollar amount to
the cent), so this becomes a pure health check on every later run -- it
will not silently overwrite real accumulated cash.
```

with:

```
Idempotent per tier: only ever WRITES a fresh seed into a tier that
currently reads exactly $0.0, leaving every other tier's accumulated
ledger cash untouched. A tier that's non-zero because it already holds a
committed position (or has traded since its own seed) is never
overwritten here -- see pools_drifted() below for the separate check that
catches a tier that's non-zero but numerically wrong.
```

- [ ] **Step 4: Update `main()`'s seeding branch to seed only the zero tiers, leaving the rest of the dict untouched**

Replace the tail of `main()` (from `seed = compute_seed_split(...)` through the old `still_unfunded` check) with:

```python
    to_seed = zero_tiers(tier_pools)
    if to_seed:
        seed = compute_seed_split(
            total_equity, market_value_by_symbol,
            symbol_tier=SYMBOL_TIER, tier1_symbol_weights=TIER1_SYMBOL_WEIGHTS,
        )
        for tier in to_seed:
            tier_pools[tier] = seed[tier]
        save_tier_pools(tier_pools, state_dir=state_dir)
        print(f"seeded previously-unfunded tiers {sorted(to_seed)} from equity={total_equity}: "
              f"{ {t: tier_pools[t] for t in to_seed} }")
```

(This intermediate step deliberately still returns `_write_github_output("healthy")` unconditionally after — Task 2 replaces that trailing line with the drift check. If implementing task-by-task, leave `_write_github_output("healthy"); return 0` at the end of `main()` for now so Task 1 is independently testable and shippable.)

You'll also need to move the `to_seed = zero_tiers(tier_pools)` computation up to where `tier_pools` is first loaded (replacing the old `if not pools_are_unfunded(tier_pools):` early-return block) — the full `main()` after this step:

```python
def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    state_dir = os.environ.get("GRAYWIND_STATE_DIR", "state")

    if not SYMBOL_TIER and not TIER1_SYMBOL_WEIGHTS:
        print("no tier symbols configured; nothing to seed or guard")
        _write_github_output("healthy")
        return 0

    tier_pools = load_tier_pools(state_dir=state_dir)
    to_seed = zero_tiers(tier_pools)

    if not to_seed:
        print(f"tier pools already funded ({tier_pools}); nothing to do")
        _write_github_output("healthy")
        return 0

    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY/ALPACA_API_SECRET not set; cannot seed", file=sys.stderr)
        _write_github_output("unhealthy")
        return 0

    try:
        trading_client = TradingClient(api_key, api_secret, paper=True)
        account = trading_client.get_account()
        total_equity = float(account.equity)
        positions = trading_client.get_all_positions()
        market_value_by_symbol = {p.symbol: float(p.market_value) for p in positions}
    except Exception as exc:
        print(f"ERROR: could not fetch account/positions from Alpaca: {exc}", file=sys.stderr)
        _write_github_output("unhealthy")
        return 0

    seed = compute_seed_split(
        total_equity, market_value_by_symbol,
        symbol_tier=SYMBOL_TIER, tier1_symbol_weights=TIER1_SYMBOL_WEIGHTS,
    )
    for tier in to_seed:
        tier_pools[tier] = seed[tier]
    save_tier_pools(tier_pools, state_dir=state_dir)
    print(f"seeded previously-unfunded tiers {sorted(to_seed)} from equity={total_equity}: "
          f"{ {t: tier_pools[t] for t in to_seed} }")

    _write_github_output("healthy")
    return 0
```

Note: this intermediate version still early-returns when `to_seed` is empty (same as before Task 1), so `test_main_skips_seeding_when_pools_already_funded`'s `mock_cls` assertions won't be right until Task 2 changes this early-return. Leave that one test adjusted-but-expected-to-still-need-Task-2 for now, or just implement Task 1 and Task 2 back to back before running the full file's tests.

- [ ] **Step 5: Run the full test file, confirm the Task-1-scoped tests pass**

Run: `.venv/bin/python -m pytest tests/test_seed_tier_pools.py -v`
Expected: `test_partially_funded_pool_seeds_only_the_zero_tiers`, `test_all_zero_are_all_zero_tiers`, `test_only_the_zero_tiers_are_returned`, `test_no_zero_tiers_returns_empty_set`, and the pre-existing `test_main_seeds_pools_from_live_equity_and_positions` / `test_main_reports_unhealthy_when_credentials_missing` / `test_main_reports_unhealthy_when_alpaca_call_fails` / `test_main_is_a_noop_when_no_tier_symbols_are_configured` all PASS. `test_main_skips_seeding_when_pools_already_funded` may still fail on the `mock_cls` assertion — that's expected until Task 2.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all passing except possibly the one test noted above, carried into Task 2.

- [ ] **Step 7: Commit**

```bash
git add scripts/seed_tier_pools.py tests/test_seed_tier_pools.py
git commit -m "fix: seed each unfunded tier pool independently, not only when all three are \$0

The \$100k account's tier 2 holds a committed AAPL position, so the old
all-or-nothing pools_are_unfunded() check never fired -- tiers 1 and 3
have been stuck at \$0 since the tier-pool-scoped sizing model shipped.
Seeds only the tiers currently reading exactly \$0, leaving every other
tier's accumulated ledger cash untouched."
```

---

### Task 2: Add the tier-pool drift alarm and the `GITHUB_TOKEN` guard (punch-list item 6, parts a and b)

**Files:**
- Modify: `scripts/seed_tier_pools.py`
- Modify: `live_loop.py`
- Test: `tests/test_seed_tier_pools.py`
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Consumes: `_committed_by_tier` from Task 1.
- Produces: `pools_drifted(tier_pools, total_equity, market_value_by_symbol, target_weights=TIER_TARGET_WEIGHTS, symbol_tier=None, tier1_symbol_weights=None, tolerance_fraction=0.05) -> bool`.

- [ ] **Step 1: Write the failing test for `pools_drifted`**

Add to `tests/test_seed_tier_pools.py`:

```python
# --- pools_drifted ---

def test_pools_matching_target_are_not_drifted():
    assert pools_drifted(
        tier_pools={1: 70_000.0, 2: 5_000.0, 3: 10_000.0},
        total_equity=100_000.0,
        market_value_by_symbol={"AAPL": 15_000.0},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        symbol_tier={"AAPL": 2},
    ) is False


def test_pool_far_below_target_share_is_drifted():
    # tier 2 should be worth ~20% of 100k (~$20k incl. committed); it's
    # only worth $5k cash + $2k committed = $7k, a $13k gap on a 5%
    # ($5k) tolerance.
    assert pools_drifted(
        tier_pools={1: 70_000.0, 2: 5_000.0, 3: 10_000.0},
        total_equity=100_000.0,
        market_value_by_symbol={"AAPL": 2_000.0},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        symbol_tier={"AAPL": 2},
    ) is True


def test_small_gap_within_tolerance_is_not_drifted():
    assert pools_drifted(
        tier_pools={1: 69_500.0, 2: 20_000.0, 3: 10_000.0},
        total_equity=100_000.0,
        market_value_by_symbol={},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        tolerance_fraction=0.05,
    ) is False
```

- [ ] **Step 2: Run, confirm failure**

Run: `.venv/bin/python -m pytest tests/test_seed_tier_pools.py -k drifted -v`
Expected: FAIL with `NameError: name 'pools_drifted' is not defined`.

- [ ] **Step 3: Implement `pools_drifted`**

Add to `scripts/seed_tier_pools.py`, after `zero_tiers`:

```python
DRIFT_TOLERANCE_FRACTION = 0.05  # 5% of total account equity, either direction


def pools_drifted(tier_pools, total_equity, market_value_by_symbol, target_weights=TIER_TARGET_WEIGHTS,
                   symbol_tier=None, tier1_symbol_weights=None,
                   tolerance_fraction=DRIFT_TOLERANCE_FRACTION):
    """True if any tier's pool cash plus its committed positions has drifted
    from its target share of total account equity by more than
    tolerance_fraction * total_equity. Catches a tier that reads non-zero
    but numerically wrong -- e.g. an accounting bug in live_loop.py's
    incremental tier_pools debit/credit -- which zero_tiers() can never see,
    since it only looks for exactly $0.0. Deliberately does not correct
    anything; this is detection only (punch-list item 6b), matching the
    same "report, don't build a framework" scope as item 5.
    """
    symbol_tier = symbol_tier if symbol_tier is not None else {}
    tier1_symbol_weights = tier1_symbol_weights if tier1_symbol_weights is not None else {}
    committed = _committed_by_tier(market_value_by_symbol, symbol_tier, tier1_symbol_weights)
    tolerance = total_equity * tolerance_fraction
    for tier, weight in target_weights.items():
        actual = tier_pools.get(tier, 0.0) + committed.get(tier, 0.0)
        target = total_equity * weight
        if abs(actual - target) > tolerance:
            return True
    return False
```

- [ ] **Step 4: Run, confirm the three new tests pass**

Run: `.venv/bin/python -m pytest tests/test_seed_tier_pools.py -k drifted -v`
Expected: PASS.

- [ ] **Step 5: Wire the drift check into `main()`, and always fetch live state when credentials exist**

Replace `main()`'s body (from the `tier_pools = load_tier_pools(...)` line to the end) with:

```python
    tier_pools = load_tier_pools(state_dir=state_dir)
    to_seed = zero_tiers(tier_pools)

    if not api_key or not api_secret:
        if to_seed:
            print("ERROR: ALPACA_API_KEY/ALPACA_API_SECRET not set; cannot seed", file=sys.stderr)
            _write_github_output("unhealthy")
        else:
            print(f"tier pools already funded ({tier_pools}); nothing to seed, and no "
                  "credentials available to run the drift check")
            _write_github_output("healthy")
        return 0

    try:
        trading_client = TradingClient(api_key, api_secret, paper=True)
        account = trading_client.get_account()
        total_equity = float(account.equity)
        positions = trading_client.get_all_positions()
        market_value_by_symbol = {p.symbol: float(p.market_value) for p in positions}
    except Exception as exc:
        print(f"ERROR: could not fetch account/positions from Alpaca: {exc}", file=sys.stderr)
        _write_github_output("unhealthy")
        return 0

    if to_seed:
        seed = compute_seed_split(
            total_equity, market_value_by_symbol,
            symbol_tier=SYMBOL_TIER, tier1_symbol_weights=TIER1_SYMBOL_WEIGHTS,
        )
        for tier in to_seed:
            tier_pools[tier] = seed[tier]
        save_tier_pools(tier_pools, state_dir=state_dir)
        print(f"seeded previously-unfunded tiers {sorted(to_seed)} from equity={total_equity}: "
              f"{ {t: tier_pools[t] for t in to_seed} }")

    if pools_drifted(tier_pools, total_equity, market_value_by_symbol,
                      target_weights=TIER_TARGET_WEIGHTS,
                      symbol_tier=SYMBOL_TIER, tier1_symbol_weights=TIER1_SYMBOL_WEIGHTS):
        print(f"WARNING: tier pools have drifted from target allocation -- pools={tier_pools} "
              f"total_equity={total_equity}", file=sys.stderr)
        _write_github_output("unhealthy")
        return 0

    _write_github_output("healthy")
    return 0
```

This is a deliberate behavior change worth calling out in the commit: `main()` now calls the Alpaca API on every run (to check drift), not only when a tier needs seeding. That's one extra read-only API call per ~15-30 min cycle per account — acceptable for a personal paper-trading account, and the only way to detect item 6(b)'s "non-zero but wrong" case at all.

- [ ] **Step 6: Fix the now-correct `test_main_skips_seeding_when_pools_already_funded`**

This test from Task 1 should now pass as written (it already expects `mock_cls` to be called and asserts the pools are unchanged). Run it directly:

Run: `.venv/bin/python -m pytest tests/test_seed_tier_pools.py -k skips_seeding -v`
Expected: PASS.

- [ ] **Step 7: Run the full seed_tier_pools test file and the full suite**

Run: `.venv/bin/python -m pytest tests/test_seed_tier_pools.py -v && .venv/bin/python -m pytest -q`
Expected: all passing.

- [ ] **Step 8: Write the failing test for the `GITHUB_TOKEN` guard in `live_loop.py`**

There is no existing test for this guard at all (confirmed: `grep -n "not all\|are not set in the environment" tests/test_live_loop.py` returns nothing) — `test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs` (around line 1263) shows the general pattern other `main()` tests use: `patch("live_loop.is_market_hours", return_value=True)` plus `patch.dict(os.environ, {...})`. The guard fires before any of `main()`'s other I/O, so this test needs almost none of that other file's heavy mocking:

```python
def test_main_fails_when_github_token_is_blank():
    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k", "GITHUB_TOKEN": "",
         }):
        assert live_loop.main() == 1
```

- [ ] **Step 9: Run, confirm failure**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -k github_token_is_blank -v`
Expected: FAIL — currently `main()` proceeds past the guard since `GITHUB_TOKEN` isn't checked yet, and returns something other than `1` (likely raises or returns 0 further down, since `TradingClient(api_key, api_secret, ...)` etc. below aren't mocked in this minimal test — that's fine, it just needs to fail differently than the expected `== 1` before the fix).

- [ ] **Step 10: Implement the guard**

In `live_loop.py`, change lines 960-969 from:

```python
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    fred_api_key = os.environ.get("FRED_API_KEY")
    finnhub_api_key = os.environ.get("FINNHUB_API_KEY")
    if not all([api_key, api_secret, fred_api_key, finnhub_api_key]):
        print("ERROR: one or more required API keys are not set in the environment", file=sys.stderr)
        return 1
    deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner_username = repo.split("/")[0] if repo else ""
```

to:

```python
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    fred_api_key = os.environ.get("FRED_API_KEY")
    finnhub_api_key = os.environ.get("FINNHUB_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")
    if not all([api_key, api_secret, fred_api_key, finnhub_api_key, github_token]):
        print("ERROR: one or more required API keys are not set in the environment", file=sys.stderr)
        return 1
    deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner_username = repo.split("/")[0] if repo else ""
```

(Just moves `github_token`'s read above the guard and adds it to the `all([...])` list — a blank/unset `GITHUB_TOKEN` now fails the whole job loudly at startup, the same way a blank `ALPACA_API_KEY` already does, instead of causing every trade-approval GitHub API call to fail silently, per-symbol, for the rest of the day.)

- [ ] **Step 11: Run, confirm pass, then run the full suite**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v && .venv/bin/python -m pytest -q`
Expected: all passing.

- [ ] **Step 12: Commit**

```bash
git add scripts/seed_tier_pools.py live_loop.py tests/test_seed_tier_pools.py tests/test_live_loop.py
git commit -m "feat: add tier-pool drift alarm and GITHUB_TOKEN presence guard

pools_drifted() catches a tier that's non-zero but numerically wrong --
the zero-only check from the previous commit can't see this. live_loop.py
now fails loudly on a blank GITHUB_TOKEN instead of letting every
trade-approval GitHub call fail silently per-symbol (punch-list item 6,
parts a and b)."
```

---

### Task 3: Document the small-account 50%-position-cap reachability finding (punch-list item 5)

**Files:**
- Test: `tests/test_position_sizing.py` (confirmed already exists — add the new test to it, following its existing style/fixtures.)

**Interfaces:**
- No production code interface changes — this task adds one pinned regression test and nothing else, per the advisor's explicit framing: *"'The 50% cap is dead by construction under pool scoping' is a legitimate and more useful outcome than manufacturing a trade to trip it."*

- [ ] **Step 1: Confirm the finding with a direct calculation before writing anything**

The small account's total equity is $2,000.00 (confirmed via `git show origin/main:state/small/tier_pools.csv`: `1,1400.0 / 2,394.67 / 3,203.78`, summing to `$1,998.45` plus any open position value). `TIER_TARGET_WEIGHTS = {1: 0.70, 2: 0.20, 3: 0.10}` means every tier's pool equity is a fraction of $2,000 — the largest (tier 1, 70%) is $1,400, still below `PositionSizer`'s `small_account_threshold=2000.0` default (`graywind_strategy/risk/position_sizing.py:23`). Since `live_loop.py:554`'s `sizing_equity = tier_pools[tier] + committed` is what actually reaches `PositionSizer.shares_to_buy` (via `decide_trade`'s `account_equity=sizing_equity` at line 575) — not the account's total equity — the cap's `account_equity < self.small_account_threshold` condition (`position_sizing.py:51`) is true for every tier, every time, for this account. There is no way to construct a real trade where it's `False`, because no single tier's pool can reach $2,000 while the whole account sits at $2,000.

- [ ] **Step 2: Write the pinned regression test**

```python
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.tier_config import TIER_TARGET_WEIGHTS


def test_small_account_tier_pools_never_clear_the_small_account_threshold():
    """Documents graywind-critical-review-punch-list-execution-handoff.md
    item 5's finding (re-confirmed 2026-09-16, see
    docs/superpowers/plans/2026-09-16-graywind-punch-list.md Task 3):
    PositionSizer.shares_to_buy receives *pool* equity
    (tier_pools[tier] + committed), never whole-account equity. The $2k
    account's total equity split 70/20/10 puts every tier's pool equity
    below small_account_threshold=2000.0 by construction -- there is no
    real trade where the 50% position-value cap is OFF for this account.
    The cap isn't guarding a rare edge case here; it's permanently active.
    No production code change follows from this finding.
    """
    small_account_equity = 2_000.0
    sizer = PositionSizer()
    for tier, weight in TIER_TARGET_WEIGHTS.items():
        pool_equity = small_account_equity * weight
        assert pool_equity < sizer.small_account_threshold, (
            f"tier {tier}'s pool equity ({pool_equity}) reached the small-account "
            "threshold -- the cap-is-always-on finding may no longer hold; re-investigate"
        )
```

- [ ] **Step 3: Run, confirm it passes as a live-verified assertion (not a red-to-green TDD cycle — this test documents existing, already-correct behavior)**

Run: `.venv/bin/python -m pytest tests/test_position_sizing.py -k small_account_threshold -v`
Expected: PASS immediately (no production code changes in this task).

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all passing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_position_sizing.py
git commit -m "test: pin the finding that the small account's 50% cap is always active

Pool-scoped sizing means every tier's equity basis for the \$2k account
sits below small_account_threshold=2000.0 by construction -- there's no
real trade that exercises the cap's off state. Investigation-only per
punch-list item 5; no production code changes."
```

---

### Task 4: Validate and flip the 6-symbol sector-engine roster (punch-list item 7 / "roster flip") — **blocked, needs Alpaca credentials**

**This task cannot be executed from this session** — `data/roster/*.csv` (gitignored, not in this checkout) needs `scripts/fetch_roster_data.py`, which requires `ALPACA_API_KEY`/`ALPACA_API_SECRET` in the environment, and this local shell has neither. Whoever picks this up needs either their own Alpaca paper-trading keys locally, or to run these as a `workflow_dispatch` job if one exists for this purpose (check `.github/workflows/` first — none currently appear dedicated to this; if none exists, running locally with real keys is the only path).

**Files:**
- Modify: `live_loop.py` (`WATCHLIST`, and only if the backtest clears — do not touch `TIER1_SYMBOL_WEIGHTS`; none of the 6 candidates are tier-1 symbols per `graywind_strategy/sector_config.py`'s existing tags)

**Steps once credentials are available:**

- [ ] **Step 1: Fetch the roster and sector data**

```bash
export ALPACA_API_KEY=...
export ALPACA_API_SECRET=...
.venv/bin/python scripts/fetch_roster_data.py
.venv/bin/python scripts/fetch_sector_data.py  # if data/sector/*.csv needs refreshing too — check timestamps first, xle/xlk/xlv already exist locally
```

- [ ] **Step 2: Run the out-of-sample validation for all 6 candidates plus the existing roster**

```bash
.venv/bin/python scripts/validate_sector_engine.py
```

Report the full per-symbol output. `graywind_strategy/backtest_gate.py`'s `validate_symbol_backtest` (called from `tier_config.py`'s `validate_symbol_addition`) is the actual pass/fail gate — a symbol that fails its DSR bar does not ship, per the advisor's explicit instruction: *"Run them and report per-symbol results; a symbol that fails the DSR bar doesn't ship."*

- [ ] **Step 3: Re-verify the `tier=None` duplicate-order guard actually holds**

The guard lives at `live_loop.py:589-607` (`if tier is None:` refusal in the buy-proposal branch). Read the SDD ledger history around commit `1798308` (search `git log --all --grep=1798308` or check `.superpowers/sdd/` for the punch-list-item-7 review that reportedly fixed the "armed by the next watchlist expansion" critical finding) before trusting the note that it's already fixed — re-verify directly against current `live_loop.py`, not from memory of the commit message.

- [ ] **Step 4: Confirm no trade-approval issues are in flight before touching `WATCHLIST`**

```bash
gh issue list -R nguyenminhthanh0403-hub/graywind --label pending-trade --state open
```

If any are open (as of 2026-09-16, #18 and #19 are — check current state, these resolve within a day or two of opening per the existing cadence), either wait for them to resolve or explicitly re-verify the `tier=None` guard covers a roster change landing mid-flight before proceeding.

- [ ] **Step 5: If every candidate symbol clears the backtest gate, flip `WATCHLIST`**

In `live_loop.py`, change:

```python
WATCHLIST = ["AAPL", "SERV"]
```

to include only the symbols that passed Step 2's validation — do not add a symbol that failed, even if others in the same sector passed.

- [ ] **Step 6: Run the full suite, then land outside market hours**

```bash
.venv/bin/python -m pytest -q
```

Push only outside `13:07-20:37 UTC` weekdays (the live cron's window) so the 6-symbol expansion doesn't get picked up mid-cycle.

- [ ] **Step 7: Commit**

```bash
git add live_loop.py
git commit -m "feat: expand WATCHLIST to the validated sector-engine roster

<list the symbols that actually passed Step 2's backtest gate here --
do not commit this message unverified>"
```

---

### Task 5: Memory and docs cleanup (no code) — do last

- [ ] Mark sector-engine subsystems 2 (external financial data) and 3 (YouTube-transcript signal) as ruled out / won't-do in the `project-graywind-sector-engine.md` memory file.
- [ ] Mark the Graywind Performance Reports sub-project 3 ("personal advising UI") as redirected to the separate MAVIS effort rather than built inside Graywind, in `project-graywind-performance-reports.md` and `project-mavis-cloud-avatar.md`.
- [ ] Manually close issue #8 (orphaned since 2026-09-10, `close_issue`'s expiry-path failure left it open with nothing tracking it locally — see the "Re-verified facts" section above):

```bash
gh issue close 8 -R nguyenminhthanh0403-hub/graywind -c "Closing manually -- this proposal expired on the bot's side (no longer in pending_trades.csv) but close_issue failed silently on expiry (best-effort by design, see live_loop.py:822-828's comment). No action needed; see docs/superpowers/graywind-critical-review-punch-list-execution-handoff.md."
```

---

## Self-review notes (writing-plans skill checklist, run against this plan)

- **Spec coverage:** All 6 items from the advisor's ordering are covered — NFCI (re-verified fine, no task needed), tier-pool+reanchor (Task 1, resolved as a single change per the double-counting warning), item 6 (Task 2, scoped to the two sub-parts with live evidence — GITHUB_TOKEN and drift; issue #8's closure is a manual step in Task 5, not new alarm infrastructure, matching "don't build a framework"), item 5 (Task 3), roster flip (Task 4, blocked on credentials), memory/docs (Task 5).
- **Double-counting check:** Task 1 is the only place `tier_pools.csv` gets written from a fresh equity computation, and it only ever touches tiers that are currently exactly `$0`. Task 2 adds detection (not a second write path). `live_loop.py`'s own `sizing_equity`/`tier1_equity` computations are never modified by this plan — they inherit correctness once Task 1 lands, which is the single-authoritative-basis design the advisor asked for.
- **Placeholder scan:** no TBD/"add error handling"/"similar to Task N" — every step has real code or a real shell command.
