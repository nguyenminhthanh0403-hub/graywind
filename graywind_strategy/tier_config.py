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

assert not (set(SYMBOL_TIER) & set(TIER1_SYMBOL_WEIGHTS)), (
    "SYMBOL_TIER and TIER1_SYMBOL_WEIGHTS must be disjoint -- a symbol cannot be both "
    "an intraday tier-2/3 symbol and a tier-1 buy-and-hold symbol"
)
