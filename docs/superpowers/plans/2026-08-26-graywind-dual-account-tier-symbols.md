# Graywind Dual-Account Rollout + Tier Symbol Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate Graywind's inert 70/20/10 tier config with real symbols behind an objective
market-cap/volume/sector guardrail, and stand up a second Alpaca paper account ($2k) running
the same pipeline as the existing $100k account, both visible side by side on the dashboard.

**Architecture:** A new guardrail module inside `tier_config.py` (pure validation logic + thin
Finnhub/Alpaca I/O wrappers, same pure/IO split this codebase already uses in
`earnings_gate.py` and `tier1_rebalance.py`) populates `SYMBOL_TIER`/`TIER1_SYMBOL_WEIGHTS`.
Multi-account support is a small, additive change: `state_store.py`/`dashboard_export.py`
already accept a `state_dir`/`export_dir` parameter, so `live_loop.py` just needs to read one
new environment variable and thread it through; the workflow gets a second, sequential job
(`needs:` — avoiding a git-push race two parallel jobs would hit); the dashboard gets a second
data-fetch and a second rendered column.

**Tech Stack:** Python 3.12/3.14, `pytest`, `unittest.mock`, `requests` — no new dependencies.
Vanilla JS + D3 for `index.html` (no test framework in this repo for it — manual browser
verification, matching this project's existing precedent for dashboard changes).

**Spec:** `docs/superpowers/specs/2026-08-26-graywind-dual-account-tier-symbols-design.md`

## Global Constraints

- TDD (red/green) for every Python change — this project's existing convention.
- Run tests with the project's venv: `.venv/bin/python -m pytest tests/ -q` — plain `python3`
  lacks `yfinance` and other deps and fails to even collect several test files.
- Reuse `graywind_strategy.risk.position_sizing.QTY_DECIMALS` if any new fractional-quantity
  rounding is needed — none is expected in this plan, but don't introduce a second constant if
  it turns out to be.
- Guardrail bands (exact, from the spec): tier 2 — market cap floor $2,000,000,000, min avg
  daily volume 500,000 shares; tier 3 — market cap floor $300,000,000, min avg daily volume
  100,000 shares; both tiers — max 3 symbols per sector tag. Tier 1 has no guardrail (ETF-only
  by design).
- Starter symbols (already verified against live data during brainstorming, not to be
  re-litigated): `SYMBOL_TIER = {"AAPL": 2, "SERV": 3}`, `TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}`.
  `SYMBOL_SECTOR["SERV"] = "robotics"` (new sector tag).
- `live_loop.WATCHLIST` becomes `["AAPL", "SERV"]` — `SPY` moves out entirely (handled by the
  existing monthly `tier1_rebalance` path, not the intraday loop).
- New GitHub secrets `ALPACA_API_KEY_SMALL` / `ALPACA_API_SECRET_SMALL` must exist before the
  second workflow job can run — **this is a manual step for the user** (`gh secret set`,
  outside any task below) and is not part of this plan's automatable work. Do not attempt to
  set these secrets yourself.

---

## Task 1: Tier symbol guardrail + populate tier_config.py

**Files:**
- Modify: `graywind_strategy/tier_config.py`
- Test: `tests/test_tier_config.py` (new file)

**Interfaces:**
- Produces: `GuardrailViolation(Exception)`, `TIER_GUARDRAILS: dict`,
  `MAX_SYMBOLS_PER_SECTOR: int`, `sector_counts_for_tier(tier, symbol_tier=None,
  sector_map=SYMBOL_SECTOR) -> dict[str, int]`, `check_guardrail(tier, market_cap, avg_volume,
  sector, existing_sector_counts) -> None` (raises `GuardrailViolation` on failure),
  `fetch_market_cap(symbol, finnhub_api_key, session=requests) -> float`,
  `fetch_avg_volume(data_client, symbol, lookback_days=20) -> float`,
  `validate_symbol_addition(symbol, tier, finnhub_api_key, data_client, sector,
  symbol_tier=None, sector_map=SYMBOL_SECTOR, session=requests) -> None` (raises on failure).
  `SYMBOL_TIER = {"AAPL": 2, "SERV": 3}`, `TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}`.
- Consumes: `graywind_strategy.sector_config.SYMBOL_SECTOR` (Task 2 adds the `SERV` entry this
  task's tests reference — do Task 2 first, or stub the entry locally in this task's tests if
  doing Task 1 first is preferred; either order works since the two files don't import each
  other's test-time state).

- [ ] **Step 1: Write the failing tests for the pure guardrail logic**

Create `tests/test_tier_config.py`:

```python
import pytest
from unittest.mock import MagicMock

from graywind_strategy.tier_config import (
    GuardrailViolation, TIER_GUARDRAILS, MAX_SYMBOLS_PER_SECTOR,
    sector_counts_for_tier, check_guardrail, fetch_market_cap, fetch_avg_volume,
    validate_symbol_addition, SYMBOL_TIER, TIER1_SYMBOL_WEIGHTS,
)


def test_symbol_tier_has_the_confirmed_starter_symbols():
    assert SYMBOL_TIER == {"AAPL": 2, "SERV": 3}


def test_tier1_symbol_weights_has_spy_at_full_weight():
    assert TIER1_SYMBOL_WEIGHTS == {"SPY": 1.0}


def test_check_guardrail_passes_when_all_bands_clear():
    # AAPL-like numbers: huge cap, huge volume, sector not yet crowded.
    check_guardrail(
        tier=2, market_cap=3_000_000_000_000, avg_volume=40_000_000,
        sector="tech", existing_sector_counts={"tech": 2},
    )  # no exception == pass


def test_check_guardrail_rejects_market_cap_below_tier2_floor():
    with pytest.raises(GuardrailViolation, match="market cap"):
        check_guardrail(
            tier=2, market_cap=1_999_999_999, avg_volume=1_000_000,
            sector="tech", existing_sector_counts={},
        )


def test_check_guardrail_rejects_market_cap_below_tier3_floor():
    # Mirrors QUIK's real rejected numbers from brainstorming: ~$208M cap, fails the $300M floor.
    with pytest.raises(GuardrailViolation, match="market cap"):
        check_guardrail(
            tier=3, market_cap=208_270_000, avg_volume=281_806,
            sector="tech", existing_sector_counts={},
        )


def test_check_guardrail_accepts_market_cap_exactly_at_tier3_floor():
    check_guardrail(
        tier=3, market_cap=300_000_000, avg_volume=100_000,
        sector="robotics", existing_sector_counts={},
    )  # boundary is inclusive -- no exception == pass


def test_check_guardrail_rejects_volume_below_tier3_floor():
    with pytest.raises(GuardrailViolation, match="volume"):
        check_guardrail(
            tier=3, market_cap=500_000_000, avg_volume=99_999,
            sector="robotics", existing_sector_counts={},
        )


def test_check_guardrail_accepts_serv_like_numbers_for_tier3():
    # SERV's real researched numbers from brainstorming: ~$423M cap, ~5.2M avg volume.
    check_guardrail(
        tier=3, market_cap=422_940_000, avg_volume=5_217_680,
        sector="robotics", existing_sector_counts={},
    )  # no exception == pass


def test_check_guardrail_rejects_when_sector_already_at_cap():
    with pytest.raises(GuardrailViolation, match="sector"):
        check_guardrail(
            tier=2, market_cap=10_000_000_000, avg_volume=1_000_000,
            sector="tech", existing_sector_counts={"tech": MAX_SYMBOLS_PER_SECTOR},
        )


def test_check_guardrail_accepts_when_sector_just_under_cap():
    check_guardrail(
        tier=2, market_cap=10_000_000_000, avg_volume=1_000_000,
        sector="tech", existing_sector_counts={"tech": MAX_SYMBOLS_PER_SECTOR - 1},
    )  # no exception == pass


def test_sector_counts_for_tier_counts_only_matching_tier_and_known_sectors():
    fake_symbol_tier = {"AAPL": 2, "NVDA": 2, "SERV": 3}
    fake_sector_map = {"AAPL": "tech", "NVDA": "tech", "SERV": "robotics"}
    counts = sector_counts_for_tier(tier=2, symbol_tier=fake_symbol_tier, sector_map=fake_sector_map)
    assert counts == {"tech": 2}


def test_fetch_market_cap_converts_finnhub_millions_to_dollars():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 423.0}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = fetch_market_cap("SERV", "fake-key", session=fake_session)

    assert result == 423_000_000.0


def test_fetch_market_cap_raises_when_field_missing():
    fake_response = MagicMock()
    fake_response.json.return_value = {}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    with pytest.raises(GuardrailViolation, match="marketCapitalization"):
        fetch_market_cap("SERV", "fake-key", session=fake_session)


def test_fetch_avg_volume_averages_bar_volumes():
    fake_bar_1 = MagicMock(volume=100)
    fake_bar_2 = MagicMock(volume=300)
    fake_data_client = MagicMock()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [fake_bar_1, fake_bar_2],
        )
        result = fetch_avg_volume(fake_data_client, "SERV")

    assert result == 200.0


def test_fetch_avg_volume_raises_when_no_bars_returned():
    fake_data_client = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "graywind_strategy.tier_config.fetch_bars",
            lambda client, symbol, start, end: [],
        )
        with pytest.raises(GuardrailViolation, match="no bars"):
            fetch_avg_volume(fake_data_client, "SERV")


def test_validate_symbol_addition_raises_on_first_failing_check():
    fake_response = MagicMock()
    fake_response.json.return_value = {"marketCapitalization": 1.0}  # $1M -- fails every floor
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fake_data_client = MagicMock()

    with pytest.raises(GuardrailViolation, match="market cap"):
        validate_symbol_addition(
            "PENNY", tier=3, finnhub_api_key="k", data_client=fake_data_client,
            sector="tech", session=fake_session,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_tier_config.py -v`
Expected: FAIL — `ImportError` (none of these names exist in `tier_config.py` yet).

- [ ] **Step 3: Implement the guardrail module and populate the tier dicts**

Replace the full contents of `graywind_strategy/tier_config.py` with:

```python
"""Symbol-to-tier tagging for the 70/20/10 portfolio-tier split
(docs/superpowers/specs/2026-08-26-graywind-tier-allocation-design.md), plus the
objective guardrail (docs/superpowers/specs/2026-08-26-graywind-dual-account-tier-symbols-design.md)
future symbol additions must clear before being added to SYMBOL_TIER by hand.

Tier 1 = steady/safe/income (buy-and-hold, tier1_rebalance.py); tiers 2/3 =
shorter-term/gamble, routed through the existing intraday engine (decide_trade) scoped to
their own pool equity. This is a living list, not a one-time fixed roster -- new tier 2/3
symbols are meant to be added over time, each vetted via validate_symbol_addition() first.
"""
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from fetch_alpaca_data import fetch_bars
from graywind_strategy.sector_config import SYMBOL_SECTOR

ET = ZoneInfo("America/New_York")
FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"
VOLUME_LOOKBACK_DAYS = 20

TIER_GUARDRAILS = {
    2: {"market_cap_floor": 2_000_000_000, "min_avg_volume": 500_000},
    3: {"market_cap_floor": 300_000_000, "min_avg_volume": 100_000},
}
MAX_SYMBOLS_PER_SECTOR = 3


class GuardrailViolation(Exception):
    pass


SYMBOL_TIER = {"AAPL": 2, "SERV": 3}  # symbol -> 1 | 2 | 3

TIER_TARGET_WEIGHTS = {1: 0.70, 2: 0.20, 3: 0.10}  # fraction of total account capital

TIER1_SYMBOL_WEIGHTS = {"SPY": 1.0}  # symbol -> target weight within tier 1

assert not (set(SYMBOL_TIER) & set(TIER1_SYMBOL_WEIGHTS)), (
    "SYMBOL_TIER and TIER1_SYMBOL_WEIGHTS must be disjoint -- a symbol cannot be both "
    "an intraday tier-2/3 symbol and a tier-1 buy-and-hold symbol"
)


def sector_counts_for_tier(tier, symbol_tier=None, sector_map=SYMBOL_SECTOR):
    if symbol_tier is None:
        symbol_tier = SYMBOL_TIER
    counts = {}
    for symbol, sym_tier in symbol_tier.items():
        if sym_tier != tier:
            continue
        sector = sector_map.get(symbol)
        if sector is not None:
            counts[sector] = counts.get(sector, 0) + 1
    return counts


def check_guardrail(tier, market_cap, avg_volume, sector, existing_sector_counts):
    bands = TIER_GUARDRAILS[tier]
    if market_cap < bands["market_cap_floor"]:
        raise GuardrailViolation(
            f"market cap {market_cap} below tier {tier} floor {bands['market_cap_floor']}"
        )
    if avg_volume < bands["min_avg_volume"]:
        raise GuardrailViolation(
            f"avg daily volume {avg_volume} below tier {tier} floor {bands['min_avg_volume']}"
        )
    if existing_sector_counts.get(sector, 0) >= MAX_SYMBOLS_PER_SECTOR:
        raise GuardrailViolation(
            f"sector '{sector}' already has {MAX_SYMBOLS_PER_SECTOR} symbols in tier {tier}"
        )


def fetch_market_cap(symbol, finnhub_api_key, session=requests):
    response = session.get(
        FINNHUB_PROFILE_URL, params={"symbol": symbol, "token": finnhub_api_key}, timeout=10
    )
    response.raise_for_status()
    data = response.json()
    if "marketCapitalization" not in data:
        raise GuardrailViolation(
            f"Finnhub profile2 response for {symbol} has no marketCapitalization field"
        )
    return data["marketCapitalization"] * 1_000_000  # Finnhub reports this in millions of USD


def fetch_avg_volume(data_client, symbol, lookback_days=VOLUME_LOOKBACK_DAYS):
    now = datetime.now(ET)
    bars = fetch_bars(data_client, symbol, now - timedelta(days=lookback_days), now)
    if not bars:
        raise GuardrailViolation(f"no bars returned for {symbol}, cannot compute avg volume")
    return statistics.mean(bar.volume for bar in bars)


def validate_symbol_addition(symbol, tier, finnhub_api_key, data_client, sector,
                              symbol_tier=None, sector_map=SYMBOL_SECTOR, session=requests):
    market_cap = fetch_market_cap(symbol, finnhub_api_key, session=session)
    avg_volume = fetch_avg_volume(data_client, symbol)
    existing_sector_counts = sector_counts_for_tier(tier, symbol_tier=symbol_tier, sector_map=sector_map)
    check_guardrail(tier, market_cap, avg_volume, sector, existing_sector_counts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_tier_config.py -v`
Expected: PASS (all tests green).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS. (`tests/test_state_store.py`/`tests/test_tier1_rebalance.py` are unaffected by
this task; if anything unrelated breaks, stop and investigate before continuing.)

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/tier_config.py tests/test_tier_config.py
git commit -m "feat: populate tier_config with guardrail-vetted starter symbols"
```

---

## Task 2: Tag SERV as a new "robotics" sector

**Files:**
- Modify: `graywind_strategy/sector_config.py`
- Test: `tests/test_sector_config.py`

**Interfaces:**
- Produces: `SYMBOL_SECTOR["SERV"] == "robotics"`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sector_config.py`:

```python
def test_symbol_sector_tags_serv_as_robotics():
    assert SYMBOL_SECTOR["SERV"] == "robotics"


def test_symbols_in_sector_returns_serv_for_robotics():
    assert symbols_in_sector("robotics") == ["SERV"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_sector_config.py -v`
Expected: FAIL — `KeyError: 'SERV'` on the first new test.

- [ ] **Step 3: Add the tag**

In `graywind_strategy/sector_config.py`, add one line to the `SYMBOL_SECTOR` dict (after the
existing `"UNH": "health",` line, before the SPY comment):

```python
    "SERV": "robotics",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sector_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/sector_config.py tests/test_sector_config.py
git commit -m "feat: tag SERV as a new robotics sector"
```

---

## Task 3: WATCHLIST update + per-account state directory

**Files:**
- Modify: `live_loop.py`
- Test: `tests/test_live_loop.py`

**Interfaces:**
- Produces: `live_loop.WATCHLIST == ["AAPL", "SERV"]`. `main()` reads
  `GRAYWIND_STATE_DIR` from the environment (default `"state"`) and passes it as `state_dir=`
  to every `state_store`/`dashboard_export` call it makes.
- Consumes: `graywind_strategy.state_store.{load_state, save_state, load_tier_pools,
  save_tier_pools, load_rebalance_state, save_rebalance_state}` (all already accept
  `state_dir=`, per Task 1's context-gathering — no changes needed to `state_store.py`
  itself).

- [ ] **Step 1: Write the failing test for GRAYWIND_STATE_DIR threading**

Add to `tests/test_live_loop.py` (near the other `main()` tests — reuse the same mocking style
as `test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs`):

```python
def test_main_threads_graywind_state_dir_env_var_into_every_state_call():
    fake_account = MagicMock()
    fake_account.equity = "2000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []

    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
             "GRAYWIND_STATE_DIR": "state/small",
         }), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state) as mock_load_state, \
         patch("live_loop.save_state") as mock_save_state, \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}) as mock_load_tier_pools, \
         patch("live_loop.save_tier_pools") as mock_save_tier_pools, \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}) as mock_load_rebalance, \
         patch("live_loop.save_rebalance_state") as mock_save_rebalance, \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.write_cycle_export"):
        result = live_loop.main()

    assert result == 0
    assert mock_load_state.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_state.call_args.kwargs["state_dir"] == "state/small"
    assert mock_load_tier_pools.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_tier_pools.call_args.kwargs["state_dir"] == "state/small"
    assert mock_load_rebalance.call_args.kwargs["state_dir"] == "state/small"
    assert mock_save_rebalance.call_args.kwargs["state_dir"] == "state/small"


def test_main_defaults_graywind_state_dir_to_state_when_env_var_unset():
    fake_account = MagicMock()
    fake_account.equity = "100000.0"
    fake_trading_client = MagicMock()
    fake_trading_client.get_account.return_value = fake_account
    fake_trading_client.get_all_positions.return_value = []

    fake_state = {"day_trade_dates": [], "day": None, "starting_equity": None, "open_positions": {}}

    with patch("live_loop.is_market_hours", return_value=True), \
         patch.dict(os.environ, {
             "ALPACA_API_KEY": "k", "ALPACA_API_SECRET": "k",
             "FRED_API_KEY": "k", "FINNHUB_API_KEY": "k",
         }, clear=False), \
         patch("live_loop.TradingClient", return_value=fake_trading_client), \
         patch("live_loop.StockHistoricalDataClient"), \
         patch("live_loop.NewsClient"), \
         patch("live_loop.load_state", return_value=fake_state) as mock_load_state, \
         patch("live_loop.save_state"), \
         patch("live_loop.load_tier_pools", return_value={1: 0.0, 2: 0.0, 3: 0.0}), \
         patch("live_loop.save_tier_pools"), \
         patch("live_loop.load_rebalance_state", return_value={"last_rebalance_month": None}), \
         patch("live_loop.save_rebalance_state"), \
         patch("live_loop.fetch_bars", return_value=[]), \
         patch("live_loop.write_cycle_export"):
        os.environ.pop("GRAYWIND_STATE_DIR", None)
        result = live_loop.main()

    assert result == 0
    assert mock_load_state.call_args.kwargs["state_dir"] == "state"
```

Also update the existing `test_symbol_exception_does_not_abort_cycle_and_save_state_still_runs`
test (it hardcodes `WATCHLIST`'s old second entry, `"SPY"`, which no longer exists once this
task ships): change every `"SPY"` in that one test function's body to `"SERV"`, i.e.:

```python
    def fake_fetch_bars(client, symbol, start, end):
        if symbol == "AAPL":
            raise RuntimeError("transient network error")
        return [_FakeBar(100.0, datetime(2024, 1, 8, 10, 0, tzinfo=ET))]
```
(unchanged — this part already refers to `"AAPL"` by name, not `"SPY"`, so it's fine as-is)
and:
```python
    # AAPL's fetch_bars raised -> AAPL never reaches decide_trade, but SERV
    # (processed next) still does -- the exception didn't abort the cycle.
    mock_decide.assert_called_once()
    assert mock_decide.call_args.kwargs["symbol"] == "SERV"
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v -k "graywind_state_dir"`
Expected: FAIL — `AssertionError` (`state_dir` kwarg is currently absent/wrong since `main()`
doesn't pass it yet).

- [ ] **Step 3: Implement the change in live_loop.py**

Change the `WATCHLIST` line near the top of `live_loop.py`:

```python
WATCHLIST = ["AAPL", "SERV"]
```

In `main()`, right after the existing block that reads the other API keys from the
environment (`api_key = os.environ.get("ALPACA_API_KEY")` etc.), add:

```python
    state_dir = os.environ.get("GRAYWIND_STATE_DIR", "state")
```

Then thread `state_dir=state_dir` through every call site:

```python
    state = load_state(state_dir=state_dir)
    tier_pools = load_tier_pools(state_dir=state_dir)
    rebalance_state = load_rebalance_state(state_dir=state_dir)
```

and in the `finally` block:

```python
        save_state({
            "day_trade_dates": [d.isoformat() for d in pdt_throttle._day_trade_dates],
            "day": today.isoformat() if baseline_established else state["day"],
            "starting_equity": starting_equity if baseline_established else state["starting_equity"],
            "open_positions": open_positions,
        }, state_dir=state_dir)
        save_tier_pools(tier_pools, state_dir=state_dir)
        save_rebalance_state(rebalance_state, state_dir=state_dir)
```

(`write_cycle_export`'s `DASHBOARD_EXPORT_DIR` stays unchanged — it's per-job scratch space,
not account-specific state; see the spec's "State and dashboard-data layout" section.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_live_loop.py -v`
Expected: PASS (all tests in the file, including the updated SERV assertion).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add live_loop.py tests/test_live_loop.py
git commit -m "feat: parameterize live_loop state dir for multi-account support"
```

---

## Task 4: Second workflow job for the $2k account

**Files:**
- Modify: `.github/workflows/live-trading.yml`

**Interfaces:**
- Produces: a `live-cycle-small` job that runs after `live-cycle` completes successfully,
  trading the $2k account into `state/small/` and `dashboard-data/small/`.
- Consumes: `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL` secrets (must exist before this
  job can succeed — see Global Constraints; not created by this task).

No test framework covers this file (matches this project's existing precedent — no other task
in the codebase unit-tests workflow YAML). Validate syntactically, then verify behaviorally
post-merge via a manual `workflow_dispatch` run.

- [ ] **Step 1: Add the second job**

In `.github/workflows/live-trading.yml`, rename the existing `live-cycle` job's steps are
unchanged — add a new job **after** it (same `jobs:` block):

```yaml
  live-cycle-small:
    needs: live-cycle
    runs-on: ubuntu-latest
    steps:
      - name: Check out graywind
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run the live trading cycle
        env:
          ALPACA_API_KEY: ${{ secrets.ALPACA_API_KEY_SMALL }}
          ALPACA_API_SECRET: ${{ secrets.ALPACA_API_SECRET_SMALL }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
          FINNHUB_API_KEY: ${{ secrets.FINNHUB_API_KEY }}
          GRAYWIND_STATE_DIR: state/small
        run: python3 live_loop.py

      - name: Check whether this cycle actually ran
        id: cycle
        if: always()
        run: |
          if [ -d dashboard_export ]; then echo "ran=true" >> "$GITHUB_OUTPUT"; else echo "ran=false" >> "$GITHUB_OUTPUT"; fi

      - name: Merge this cycle's export into dashboard-data/small
        if: always() && steps.cycle.outputs.ran == 'true'
        run: python3 merge_dashboard_export.py dashboard_export dashboard-data/small

      - name: Commit and push state + dashboard data
        if: always()
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add -A state 2>/dev/null || true
          git add -A dashboard-data 2>/dev/null || true
          if git diff --cached --quiet; then
            echo "No changes this cycle; nothing to commit."
          else
            git commit -m "Update live state and dashboard data (small account) for $(date -u +%FT%H:%M)"
            git push
          fi

      - name: Report failure to the alarm issue
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            const runUrl = `${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}`;
            const { data: jobsResponse } = await github.rest.actions.listJobsForWorkflowRun({
              owner: context.repo.owner,
              repo: context.repo.repo,
              run_id: context.runId,
            });
            const failedStep = jobsResponse.jobs
              .flatMap(j => j.steps || [])
              .find(s => s.conclusion === 'failure');
            const stepName = failedStep ? failedStep.name : 'unknown step';
            const now = new Date().toISOString();
            const body = `**${now}** — failing step: **${stepName}** (small account)\nRun: ${runUrl}`;

            const { data: issues } = await github.rest.issues.listForRepo({
              owner: context.repo.owner,
              repo: context.repo.repo,
              state: 'open',
              labels: 'pipeline-alarm',
            });

            if (issues.length === 0) {
              await github.rest.issues.create({
                owner: context.repo.owner,
                repo: context.repo.repo,
                title: 'Live trading cycle is failing',
                body,
                labels: ['pipeline-alarm'],
                assignees: [context.repo.owner],
              });
            } else {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: issues[0].number,
                body,
              });
            }
```

Note: `git add -A state` / `git add -A dashboard-data` on this job's own fresh checkout
already covers the nested `state/small/`/`dashboard-data/small/` paths — no separate `git add`
targets needed. The `Ensure the pipeline-alarm label exists` and `Close the alarm issue on
success` steps are intentionally **not** duplicated in this job — the label only needs
creating once (the existing `live-cycle` job already does it every run) and having both jobs
race to close the same alarm issue on success is unnecessary; `live-cycle`'s existing
close-on-success step already covers it when both accounts are healthy. `needs: live-cycle`
means this job is skipped entirely (not run with a failure) if `live-cycle` itself fails — an
accepted trade-off from the spec: a missed cycle for one account on a bad run is not
catastrophic given the 15-minute cadence.

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/live-trading.yml'))"`
Expected: no output, exit code 0 (valid YAML). If `yaml` isn't installed in the system
Python, run `.venv/bin/python -c "..."` instead — either interpreter's YAML parser validates
syntax identically for this purpose.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/live-trading.yml
git commit -m "feat: add sequential second workflow job for the \$2k account"
```

- [ ] **Step 4: Manual verification note (not automatable here)**

After this commit is merged to `main` and the `ALPACA_API_KEY_SMALL`/`ALPACA_API_SECRET_SMALL`
secrets exist (user's manual step, see Global Constraints), trigger a `workflow_dispatch` run
by hand and confirm: `live-cycle` completes, `live-cycle-small` starts only after it, and
`state/small/`+`dashboard-data/small/` appear in the resulting commit. Leave this step
unchecked until that manual verification has actually happened.

---

## Task 5: Dashboard renders both accounts side by side

**Files:**
- Modify: `index.html`

**Interfaces:**
- Produces: two rendered columns (existing $100k account left, new $2k account right on
  desktop; stacked on narrow viewports), each independently loaded and rendered — a missing
  `dashboard-data/small/*.csv` (before the small account's first successful cycle) must not
  break the $100k column.
- Consumes: `dashboard-data/*.csv` (existing, unchanged) and `dashboard-data/small/*.csv`
  (new, written by Task 4's job once merged and live).

No test framework covers `index.html` (matches this project's existing precedent). Verify
manually in a browser after this change (see Step 5).

- [ ] **Step 1: Parameterize the render functions by an `accountId` suffix**

`buildHero`, `renderFreshness`, and `renderEquityChart` currently query fixed DOM ids
(`#chart`, `#chart-wrap`, `#freshness-dot`, `#freshness-text`). Each needs an `accountId`
parameter so two independent instances (`"100k"` and `"small"`) don't collide. In `index.html`:

Change `renderFreshness`:

```javascript
function renderFreshness(accountId, lastCycleDate) {
  const dot = document.getElementById(`freshness-dot-${accountId}`);
  const text = document.getElementById(`freshness-text-${accountId}`);
```
(keep the rest of the function body unchanged, just the two `getElementById` lines above)

Change `renderEquityChart`:

```javascript
function renderEquityChart(accountId, equityRows) {
  const svg = d3.select(`#chart-${accountId}`);
  const wrap = document.getElementById(`chart-wrap-${accountId}`);
```
(keep the rest of the function body unchanged, just the two lines above)

- [ ] **Step 2: Add a per-account wrapper that renders one column**

Replace the existing `renderApp(statusRows, equityRows, tradeRows)` function with a function
that renders into a specific container, plus a thin top-level orchestrator:

```javascript
function renderAccount(accountId, label, containerEl, statusRows, equityRows, tradeRows) {
  containerEl.innerHTML = `
    <h2 class="account-label">${label}</h2>
    <div class="freshness" id="freshness-${accountId}">
      <span class="dot" id="freshness-dot-${accountId}"></span>
      <span id="freshness-text-${accountId}">Loading…</span>
    </div>
    ${buildHero(statusRows, equityRows, tradeRows)}
    <section aria-labelledby="equity-head-${accountId}">
      <div class="section-head"><h2 id="equity-head-${accountId}">Equity Curve</h2></div>
      <div id="chart-wrap-${accountId}"><svg id="chart-${accountId}"></svg></div>
    </section>
    ${buildPositions(statusRows)}
    ${buildTradeLog(tradeRows)}`;

  renderFreshness(accountId, parseTimestamp(statusRows[0].last_cycle_timestamp));
  renderEquityChart(accountId, equityRows);
  window.addEventListener("resize", () => renderEquityChart(accountId, equityRows), { passive: true });
}

function renderAccountUnavailable(accountId, label, containerEl, message) {
  containerEl.innerHTML = `
    <h2 class="account-label">${label}</h2>
    <div class="load-error">Couldn't load this account's data (${message}).</div>`;
}
```

- [ ] **Step 3: Replace the top-level layout and `main()`**

Replace the existing `<main id="app" aria-busy="true">...</main>` block (around line 267) with
two side-by-side containers, and drop the now-redundant page-level freshness indicator (each
account renders its own):

```html
  <main id="app" aria-busy="true" class="accounts-grid">
    <section id="account-100k" class="account-col"><div class="empty-state">Loading live data…</div></section>
    <section id="account-small" class="account-col"><div class="empty-state">Loading live data…</div></section>
  </main>
```

Remove the old page-level `<div class="freshness" id="freshness">...</div>` block entirely
(around lines 260-264) — freshness is now rendered per-account inside `renderAccount`.

Add this CSS to the existing `<style>` block (side by side on desktop, stacked on narrow
viewports):

```css
.accounts-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}
@media (max-width: 900px) {
  .accounts-grid { grid-template-columns: 1fr; }
}
.account-label { margin-top: 0; }
```

Replace the existing top-level `main()` function:

```javascript
async function loadAccount(accountId, label, dataDir, containerEl) {
  try {
    const [equityRows, tradeRows, statusRows] = await Promise.all([
      loadCSV(`${dataDir}/equity_curve.csv`),
      loadCSV(`${dataDir}/trade_log.csv`),
      loadCSV(`${dataDir}/status.csv`),
    ]);
    renderAccount(accountId, label, containerEl, statusRows, equityRows, tradeRows);
  } catch (err) {
    renderAccountUnavailable(accountId, label, containerEl, err.message);
  }
}

function main() {
  loadAccount("100k", "$100k Account", "dashboard-data", document.getElementById("account-100k"));
  loadAccount("small", "$2k Account", "dashboard-data/small", document.getElementById("account-small"));
}

main();
```

The footer (`<strong>Graywind</strong> — RSI(14) + SMA(10/30) crossover strategy...`) stays
where it is, outside `#app`, as shared page-level content below both columns — no change
needed there.

- [ ] **Step 4: Commit**

```bash
git add index.html
git commit -m "feat: render both accounts side by side on the dashboard"
```

- [ ] **Step 5: Manual browser verification (not automatable here)**

Serve the repo locally (e.g. `python3 -m http.server` from the repo root) and open
`index.html` in a browser. Confirm: the existing $100k account still renders correctly in the
left column using real `dashboard-data/*.csv` on disk; the right column shows a graceful
"couldn't load" message (not a broken page) since `dashboard-data/small/` doesn't exist yet
locally; resizing the window narrow enough stacks the columns instead of squeezing them.
Leave this step unchecked until that manual check has actually happened. Full verification
with real small-account data requires Task 4's job to have run at least once in production
(GitHub Pages), which is separate from this local check.

---

## Self-review notes (for the plan author, already applied above)

- **Spec coverage:** guardrail bands ✓ (Task 1), starter symbols ✓ (Task 1), SERV sector tag
  ✓ (Task 2), WATCHLIST change ✓ (Task 3), `GRAYWIND_STATE_DIR` ✓ (Task 3), sequential
  workflow jobs ✓ (Task 4), secrets (manual, flagged not automated) ✓ (Global Constraints),
  dashboard side-by-side ✓ (Task 5). No spec section without a task.
- **Type consistency:** `state_dir` kwarg name matches `state_store.py`'s existing signatures
  exactly across Tasks 1/3. `accountId` string values (`"100k"`/`"small"`) are consistent
  across every Task 5 function call site.
- **No placeholders:** every step above contains complete, runnable code — no TBD/TODO.
