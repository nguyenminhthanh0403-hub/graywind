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

Idempotent per tier: only ever WRITES a fresh seed into a tier that
currently reads exactly $0.0, leaving every other tier's accumulated
ledger cash untouched. A tier that's non-zero because it already holds a
committed position (or has traded since its own seed) is never
overwritten here -- see pools_drifted() below for the separate check that
catches a tier that's non-zero but numerically wrong.

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


def _committed_by_tier(market_value_by_symbol, symbol_tier, tier1_symbol_weights):
    """{tier: sum of open-position market value for symbols mapped to that
    tier}, via tier1_symbol_weights for tier 1 and symbol_tier for tiers 2/3.
    Shared by compute_seed_split and pools_drifted, so the two never compute
    "what's already committed" two different ways.
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
    position's market value. Committed value per tier is the sum of market
    value for symbols mapped to that tier (tier 1 via tier1_symbol_weights,
    tiers 2/3 via symbol_tier). Floors at 0 -- a tier whose existing position
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


def clamp_seed_to_available_cash(naive_seed, to_seed, tier_pools, total_committed, total_equity):
    """compute_seed_split()'s per-tier formula (total_equity * weight -
    committed[tier]) is only correct when EVERY tier is seeded at once, from
    a ledger that starts at $0 -- its per-tier terms sum to exactly
    total_equity - total_committed, the real available cash. Seeding only a
    SUBSET of tiers (to_seed) breaks that: a sibling tier we're NOT
    touching may already hold real cash (tier_pools[t] for t not in
    to_seed), and naive_seed has no way to know that cash already exists,
    since it only subtracts each tier's own COMMITTED POSITION value, not
    other tiers' CASH. Left unclamped, this invents money that isn't
    there -- confirmed live against the $100k account: tier 2 legitimately
    accumulated $51,387.63 in cash from real closed AAPL round trips (not a
    bug -- reconciles against dashboard-data/trade_log.csv), which already
    accounts for essentially all of the account's free cash, leaving
    nothing for tiers 1 and 3 to draw from no matter what their target
    weights say.

    Scales naive_seed's entries for `to_seed` down proportionally so their
    sum never exceeds what's actually left: total_equity minus every
    tier's committed positions minus cash already sitting in tiers we
    aren't touching. If nothing is left, every seeded tier gets $0 --
    correctly leaving pools_drifted() to keep reporting unhealthy until a
    human reallocates cash across tiers or deposits more capital; this
    function only ever gives out real, currently-uncommitted cash, never
    invents it.

    Deliberately conservative, not exact: `total_committed` covers every
    tier, including ones in `to_seed`, whose own committed value
    naive_seed already netted out once via compute_seed_split. That's a
    double subtraction for a seeded tier that itself holds a position --
    it can only make `available` smaller (clamp harder) than the true
    figure, never larger, so it can under-fund a tier but never invent
    cash. Left as-is rather than fixed, since erring toward under-funding
    is the safe direction for a live trading system; see
    test_double_counted_committed_value_only_makes_the_clamp_stricter.
    """
    requested = sum(naive_seed[tier] for tier in to_seed)
    if requested <= 0:
        return {tier: naive_seed[tier] for tier in to_seed}
    already_allocated = sum(cash for tier, cash in tier_pools.items() if tier not in to_seed)
    available = max(0.0, total_equity - total_committed - already_allocated)
    if requested <= available:
        seed = {tier: naive_seed[tier] for tier in to_seed}
    else:
        scale = available / requested
        seed = {tier: naive_seed[tier] * scale for tier in to_seed}
    # Snap floating-point residue (e.g. 4.9e-12 from an available/requested
    # scale factor that should be exactly 0) down to a real $0.0. Anything
    # short of that would silently defeat zero_tiers()'s exact `== 0.0`
    # check on the next run -- the tier would never be considered
    # unfunded again, even once real cash frees up to fund it.
    return {tier: (cash if cash >= 0.01 else 0.0) for tier, cash in seed.items()}


def zero_tiers(tier_pools):
    """The tiers currently reading exactly $0.0 -- these are the only ones
    eligible for seeding. Replaces the old all-or-nothing
    pools_are_unfunded(): a tier with a pre-existing committed position
    (e.g. tier 2 holding AAPL) can be genuinely funded while a sibling tier
    (tier 1, tier 3) never received its share, and the old all-tiers check
    skipped seeding entirely whenever any single tier was non-zero.
    """
    return {tier for tier, cash in tier_pools.items() if cash == 0.0}


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
    anything; this is detection only.
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
        naive_seed = compute_seed_split(
            total_equity, market_value_by_symbol,
            symbol_tier=SYMBOL_TIER, tier1_symbol_weights=TIER1_SYMBOL_WEIGHTS,
        )
        total_committed = sum(
            _committed_by_tier(market_value_by_symbol, SYMBOL_TIER, TIER1_SYMBOL_WEIGHTS).values()
        )
        seed = clamp_seed_to_available_cash(naive_seed, to_seed, tier_pools, total_committed, total_equity)
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


if __name__ == "__main__":
    sys.exit(main())
