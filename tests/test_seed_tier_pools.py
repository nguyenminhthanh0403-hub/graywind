import os
from unittest.mock import MagicMock, patch

import pytest

from graywind_strategy.state_store import load_tier_pools, save_tier_pools
from scripts import seed_tier_pools
from scripts.seed_tier_pools import compute_seed_split, main, pools_are_unfunded


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


# --- pools_are_unfunded ---

def test_all_zero_is_unfunded():
    assert pools_are_unfunded({1: 0.0, 2: 0.0, 3: 0.0}) is True


def test_any_nonzero_tier_is_not_unfunded():
    assert pools_are_unfunded({1: 70_000.0, 2: 0.0, 3: 10_000.0}) is False


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


def test_main_skips_entirely_when_pools_already_funded(tmp_path, monkeypatch):
    state_dir = str(tmp_path / "state")
    save_tier_pools({1: 70_000.0, 2: 0.0, 3: 10_000.0}, state_dir=state_dir)
    monkeypatch.setenv("GRAYWIND_STATE_DIR", state_dir)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setattr(seed_tier_pools, "SYMBOL_TIER", {"AAPL": 2})

    with patch("scripts.seed_tier_pools.TradingClient") as mock_cls:
        assert main() == 0
        mock_cls.assert_not_called()

    assert "tier_pool_health=healthy" in _read_output(tmp_path / "gh_output")


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
    assert pools_are_unfunded(load_tier_pools(state_dir=state_dir))


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
    assert pools_are_unfunded(load_tier_pools(state_dir=state_dir))


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
