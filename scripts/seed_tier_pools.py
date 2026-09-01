"""Seeds tier_pools.csv with real starting cash the first time it's found
entirely at $0, and reports an alarm-able health status if it's ever found
that way again afterward.

Why this exists: the pool-scoping sizing code (`live_loop.py`'s
`sizing_equity = tier_pools[tier] + committed`) shipped 2026-08-25, but
nothing ever wrote real starting cash into `tier_pools.csv` -- see
docs/superpowers/graywind-tier-pool-funding-gap-handoff.md. The direct
consequences: tier 3 was fully blocked from ever sizing a position ("position
size rounds to zero shares"), tier 2 ran decoupled from its 20%-of-equity
mandate (sized only off its already-open position, not its true pool), and
tier 1's monthly rebalance computed drift against itself
(`tier1_equity = tier_pools[1] + current_holdings_value`, which is always
~0 drift when the pool is $0) -- silently frozen at whatever share count it
happened to hold, never tracking real account growth.

Idempotent by construction: only ever WRITES a fresh seed when every tier
currently reads exactly $0.0 (the actual unfunded state today). Once seeded,
at least one tier will almost certainly be non-zero (a real position's
market value essentially never lands on the exact target dollar amount to
the cent), so this becomes a pure health check on every later run -- it
will not silently overwrite real accumulated cash.

Deliberately never fails the job (mirrors check_macro_health.py) -- a
missing credential or a transient Alpaca API error here must not skip the
rest of the cycle's alarm/commit steps. It reports its status via
GITHUB_OUTPUT for the workflow's alarm step to act on instead.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.trading.client import TradingClient

from graywind_strategy.state_store import load_tier_pools, save_tier_pools
from graywind_strategy.tier_config import SYMBOL_TIER, TIER1_SYMBOL_WEIGHTS, TIER_TARGET_WEIGHTS


def compute_seed_split(total_equity, market_value_by_symbol, target_weights=TIER_TARGET_WEIGHTS,
                        symbol_tier=None, tier1_symbol_weights=None):
    """Pure: {tier: cash_to_seed} from live account equity and each open
    position's market value. Committed value per tier is the sum of market
    value for symbols mapped to that tier (tier 1 via tier1_symbol_weights,
    tiers 2/3 via symbol_tier). Floors at 0 -- a tier whose existing position
    already exceeds its target gets $0 seeded cash, never negative; this
    script does not sell anything to force a tier back to its mandate.
    """
    symbol_tier = symbol_tier if symbol_tier is not None else {}
    tier1_symbol_weights = tier1_symbol_weights if tier1_symbol_weights is not None else {}
    committed = {tier: 0.0 for tier in target_weights}
    for symbol in tier1_symbol_weights:
        committed[1] = committed.get(1, 0.0) + market_value_by_symbol.get(symbol, 0.0)
    for symbol, tier in symbol_tier.items():
        committed[tier] = committed.get(tier, 0.0) + market_value_by_symbol.get(symbol, 0.0)
    return {
        tier: max(0.0, total_equity * weight - committed.get(tier, 0.0))
        for tier, weight in target_weights.items()
    }


def pools_are_unfunded(tier_pools):
    return all(cash == 0.0 for cash in tier_pools.values())


def _write_github_output(status):
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"tier_pool_health={status}\n")


def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    state_dir = os.environ.get("GRAYWIND_STATE_DIR", "state")

    if not SYMBOL_TIER and not TIER1_SYMBOL_WEIGHTS:
        print("no tier symbols configured; nothing to seed or guard")
        _write_github_output("healthy")
        return 0

    tier_pools = load_tier_pools(state_dir=state_dir)

    if not pools_are_unfunded(tier_pools):
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
    save_tier_pools(seed, state_dir=state_dir)
    print(f"seeded tier pools from equity={total_equity}: {seed}")

    still_unfunded = pools_are_unfunded(load_tier_pools(state_dir=state_dir))
    _write_github_output("unhealthy" if still_unfunded else "healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
