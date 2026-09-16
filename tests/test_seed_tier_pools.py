import os
from unittest.mock import MagicMock, patch

import pytest

from graywind_strategy.state_store import load_tier_pools, save_tier_pools
from scripts import seed_tier_pools
from scripts.seed_tier_pools import (
    clamp_seed_to_available_cash, compute_seed_split, main, pools_drifted, zero_tiers,
)


# --- compute_seed_split (pure) ---

def test_full_target_when_nothing_is_committed():
    seed = compute_seed_split(
        total_equity=100_000.0, market_value_by_symbol={},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
    )
    assert seed == {1: 70_000.0, 2: 20_000.0, 3: 10_000.0}


def test_committed_position_is_netted_out_of_its_tier():
    seed = compute_seed_split(
        total_equity=100_000.0,
        market_value_by_symbol={"AAPL": 15_000.0},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        symbol_tier={"AAPL": 2},
    )
    assert seed[2] == pytest.approx(5_000.0)
    assert seed[1] == pytest.approx(70_000.0)
    assert seed[3] == pytest.approx(10_000.0)


def test_overshooting_tier_floors_at_zero_not_negative():
    seed = compute_seed_split(
        total_equity=100_000.0,
        market_value_by_symbol={"AAPL": 49_882.0},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        symbol_tier={"AAPL": 2},
    )
    assert seed[2] == 0.0


def test_tier1_symbol_weights_route_committed_value_into_tier_1():
    seed = compute_seed_split(
        total_equity=100_000.0,
        market_value_by_symbol={"SPY": 50_000.0},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        tier1_symbol_weights={"SPY": 1.0},
    )
    assert seed[1] == pytest.approx(20_000.0)


def test_unmapped_open_position_does_not_affect_any_tier():
    seed = compute_seed_split(
        total_equity=100_000.0,
        market_value_by_symbol={"XOM": 5_000.0},
        target_weights={1: 0.70, 2: 0.20, 3: 0.10},
        symbol_tier={"AAPL": 2},
    )
    assert seed == {1: 70_000.0, 2: 20_000.0, 3: 10_000.0}


# --- clamp_seed_to_available_cash ---

def test_no_clamping_needed_when_cash_covers_the_naive_seed():
    result = clamp_seed_to_available_cash(
        naive_seed={1: 20_000.0, 2: 5_000.0, 3: 10_000.0},
        to_seed={1, 2, 3},
        tier_pools={1: 0.0, 2: 0.0, 3: 0.0},
        total_committed=65_000.0,
        total_equity=100_000.0,
    )
    assert result == {1: 20_000.0, 2: 5_000.0, 3: 10_000.0}


def test_clamps_to_zero_when_a_sibling_tier_already_claims_all_free_cash():
    # Reproduces the real $100k account: tier 2 already holds $51,387.63 of
    # real cash (confirmed via trade_log.csv -- two genuine AAPL round
    # trips, not a bug), which already accounts for essentially all the
    # account's free cash. Naively seeding tiers 1 and 3 from
    # total_equity * weight would invent ~$31k that doesn't exist.
    result = clamp_seed_to_available_cash(
        naive_seed={1: 20_981.53, 3: 10_140.22},
        to_seed={1, 3},
        tier_pools={1: 0.0, 2: 51_387.63, 3: 0.0},
        total_committed=50_014.56,  # SPY's committed value, tier 1
        total_equity=101_402.19,
    )
    assert result[1] == pytest.approx(0.0, abs=0.01)
    assert result[3] == pytest.approx(0.0, abs=0.01)


def test_partial_clamp_scales_proportionally():
    # $10k naively requested across two tiers, but only $6k is actually
    # available -- both tiers get scaled down by the same 60% factor
    # rather than one being zeroed out arbitrarily.
    result = clamp_seed_to_available_cash(
        naive_seed={1: 8_000.0, 3: 2_000.0},
        to_seed={1, 3},
        tier_pools={1: 0.0, 2: 4_000.0, 3: 0.0},
        total_committed=0.0,
        total_equity=10_000.0,
    )
    assert result[1] == pytest.approx(4_800.0)
    assert result[3] == pytest.approx(1_200.0)


def test_clamped_to_zero_snaps_to_exactly_zero_not_floating_point_residue():
    # available/requested can land a hair above 0 instead of exactly 0
    # (float division), which would otherwise write e.g. 4.9e-12 into
    # tier_pools.csv -- zero_tiers()'s `== 0.0` check would then never see
    # that tier as unfunded again, permanently hiding it from future
    # seeding even once real cash frees up.
    result = clamp_seed_to_available_cash(
        naive_seed={1: 20_981.53, 3: 10_140.22},
        to_seed={1, 3},
        tier_pools={1: 0.0, 2: 51_387.63, 3: 0.0},
        total_committed=50_014.56,
        total_equity=101_402.19,
    )
    assert result[1] == 0.0
    assert result[3] == 0.0
    assert zero_tiers({**{1: result[1], 3: result[3]}, 2: 51_387.63}) == {1, 3}


def test_double_counted_committed_value_only_makes_the_clamp_stricter():
    # total_committed covers every tier, including ones being seeded, whose
    # own committed value naive_seed already netted out once via
    # compute_seed_split -- a deliberate double subtraction for a seeded
    # tier that itself holds a position. Verify the direction: it must
    # only ever under-fund (or exactly match), never hand out more cash
    # than compute_seed_split's own naive per-tier ceiling.
    naive_seed = {3: 5_000.0}  # e.g. 0.10 * 60_000 - 1_000 committed SERV
    result = clamp_seed_to_available_cash(
        naive_seed=naive_seed,
        to_seed={3},
        tier_pools={1: 42_000.0, 2: 12_000.0, 3: 0.0},
        total_committed=1_000.0,  # SERV's own committed value, double-subtracted
        total_equity=60_000.0,
    )
    assert result[3] <= naive_seed[3]


# --- zero_tiers ---

def test_all_zero_are_all_zero_tiers():
    assert zero_tiers({1: 0.0, 2: 0.0, 3: 0.0}) == {1, 2, 3}


def test_only_the_zero_tiers_are_returned():
    assert zero_tiers({1: 70_000.0, 2: 0.0, 3: 10_000.0}) == {2}


def test_no_zero_tiers_returns_empty_set():
    assert zero_tiers({1: 70_000.0, 2: 5_000.0, 3: 10_000.0}) == set()


# --- main() integration ---

def _mock_account(equity):
    account = MagicMock()
    account.equity = str(equity)
    return account


def _mock_position(symbol, market_value):
    position = MagicMock()
    position.symbol = symbol
    position.market_value = str(market_value)
    return position


def _read_output(github_output_path):
    with open(github_output_path) as f:
        return f.read()


def test_main_skips_seeding_when_pools_already_funded(tmp_path, monkeypatch):
    # tier2's cash (15k) + AAPL's committed value (5k) = 20k = exactly its
    # 20% target of 100k equity -- no drift, nothing to seed.
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 70_000.0, 2: 15_000.0, 3: 10_000.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2})
    monkeypatch.setattr(seed_tier_pools, "TIER_TARGET_WEIGHTS", {1: 0.70, 2: 0.20, 3: 0.10})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        mock_cls.return_value.get_account.return_value = _mock_account(100_000.0)
        mock_cls.return_value.get_all_positions.return_value = [_mock_position("AAPL", 5_000.0)]
        assert main() == 0

    assert load_tier_pools(state_dir=state_dir) == {1: 70_000.0, 2: 15_000.0, 3: 10_000.0}
    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")


def test_partially_funded_pool_seeds_only_the_zero_tiers(tmp_path, monkeypatch):
    # tier2 is already at its 20% target (50k of 250k) with no open
    # position -- reproduces the real $100k account shape (tier 2 holds
    # real cash, tiers 1/3 are stuck at $0) without conflating "cash
    # already in the pool" with "a committed position's market value",
    # which are separate, additive quantities.
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 0.0, 2: 50_000.0, 3: 0.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2, "SERV": 3})
    monkeypatch.setattr(seed_tier_pools, "TIER1_SYMBOL_WEIGHTS", {"SPY": 1.0})
    monkeypatch.setattr(seed_tier_pools, "TIER_TARGET_WEIGHTS", {1: 0.70, 2: 0.20, 3: 0.10})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        mock_cls.return_value.get_account.return_value = _mock_account(250_000.0)
        mock_cls.return_value.get_all_positions.return_value = []
        assert main() == 0

    result = load_tier_pools(state_dir=state_dir)
    assert result[1] == pytest.approx(175_000.0)   # 70% of 250k, SPY has no position yet
    assert result[2] == pytest.approx(50_000.0)    # untouched -- was already funded
    assert result[3] == pytest.approx(25_000.0)    # 10% of 250k, SERV has no position yet
    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")


def test_main_never_seeds_more_cash_than_actually_exists(tmp_path, monkeypatch):
    # The real $100k account's shape: tier 2 already holds nearly all the
    # account's free cash (a legitimate accumulation from real closed
    # trades, not a bug), tiers 1 and 3 are stuck at $0, and tier 1's only
    # committed position (SPY) eats most of the rest of total equity. This
    # is the exact scenario the naive per-tier seed formula got wrong --
    # ship this fixture and main() should now under-fund tiers 1/3 rather
    # than invent phantom cash. Numbers loosely follow the real account as
    # of 2026-09-16 (total equity ~$101,402, tier 2 cash $51,387.63, SPY
    # committed ~$50,014.56) with total_committed set so the ledger
    # reconciles almost exactly against total_equity going in.
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
        mock_cls.return_value.get_account.return_value = _mock_account(101_402.19)
        mock_cls.return_value.get_all_positions.return_value = [
            _mock_position("SPY", 50_014.56),
        ]
        assert main() == 0

    result = load_tier_pools(state_dir=state_dir)
    total_committed = 50_014.56  # SPY only -- AAPL/SERV aren't held
    # The core invariant: never claim more cash across the ledger than the
    # account actually has uncommitted. This is what the naive per-tier
    # formula violated (it would have summed to ~$82k against ~$51k real).
    assert sum(result.values()) <= 101_402.19 - total_committed + 0.01
    # Tier 2 (already funded, untouched) keeps its real, legitimately
    # earned cash -- clamping only ever affects the tiers being seeded.
    assert result[2] == pytest.approx(51_387.63)
    # With essentially no free cash left over, tiers 1 and 3 correctly
    # stay near $0 rather than being falsely marked as fixed.
    assert result[1] == pytest.approx(0.0, abs=1.0)
    assert result[3] == pytest.approx(0.0, abs=1.0)
    # And the drift alarm correctly keeps firing -- this account still
    # needs a real, human-decided cross-tier cash reallocation; this
    # script deliberately never attempts that on its own.
    assert "tier_pool_health=unhealthy" in _read_output(tmp_path / "gh_output")


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


def test_main_reports_unhealthy_when_credentials_missing(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 0.0, 2: 0.0, 3: 0.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2})

    assert main() == 0
    assert "tier_pool_health=unhealthy" in _read_output(tmp_path / "gh_output")
    # never actually wrote a seed, since it couldn't fetch equity
    assert zero_tiers(load_tier_pools(state_dir=state_dir)) == {1, 2, 3}


def test_main_reports_unhealthy_when_alpaca_call_fails(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 0.0, 2: 0.0, 3: 0.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        mock_cls.return_value.get_account.side_effect = RuntimeError("boom")
        assert main() == 0

    assert "tier_pool_health=unhealthy" in _read_output(tmp_path / "gh_output")
    assert zero_tiers(load_tier_pools(state_dir=state_dir)) == {1, 2, 3}


def test_main_seeds_pools_from_live_equity_and_positions(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 0.0, 2: 0.0, 3: 0.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2, "SERV": 3})
    monkeypatch.setattr(seed_tier_pools, "TIER1_SYMBOL_WEIGHTS", {"SPY": 1.0})
    monkeypatch.setattr(seed_tier_pools, "TIER_TARGET_WEIGHTS", {1: 0.70, 2: 0.20, 3: 0.10})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        mock_cls.return_value.get_account.return_value = _mock_account(100_000.0)
        mock_cls.return_value.get_all_positions.return_value = [
            _mock_position("SPY", 50_000.0),
            _mock_position("AAPL", 15_000.0),
        ]
        assert main() == 0

    result = load_tier_pools(state_dir=state_dir)
    assert result[1] == pytest.approx(20_000.0)   # 70% of 100k minus 50k committed SPY
    assert result[2] == pytest.approx(5_000.0)    # 20% of 100k minus 15k committed AAPL
    assert result[3] == pytest.approx(10_000.0)   # 10% of 100k, SERV has no position yet
    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")


def test_main_is_a_noop_when_no_tier_symbols_are_configured(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 0.0, 2: 0.0, 3: 0.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {})
    monkeypatch.setattr(seed_tier_pools, "TIER1_SYMBOL_WEIGHTS", {})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        assert main() == 0
        mock_cls.assert_not_called()

    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")
