"""Static symbol-to-sector tagging. Sector tags exist for FUTURE
non-volatility caveats (e.g. an energy oil-price gate, a tech
earnings-surprise gate) -- not consumed by graywind_strategy.volatility or
any confirmation-bars math (see
docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md). This
module has no dependents yet; it is scaffolding for later work.
"""

SYMBOL_SECTOR = {
    "AAPL": "tech",
    "NVDA": "tech",
    "MSFT": "tech",
    "XOM": "energy",
    "CVX": "energy",
    "JNJ": "health",
    "UNH": "health",
    # SPY is a broad-market index, not sector-specific -- deliberately
    # left out of this mapping rather than tagged with an arbitrary sector.
}


def symbols_in_sector(sector):
    return [symbol for symbol, tag in SYMBOL_SECTOR.items() if tag == sector]
