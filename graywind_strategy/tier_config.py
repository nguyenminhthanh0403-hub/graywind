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
from graywind_strategy.guardrails import GuardrailViolation
from graywind_strategy.sector_config import SYMBOL_SECTOR

ET = ZoneInfo("America/New_York")
FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"
VOLUME_LOOKBACK_DAYS = 20

TIER_GUARDRAILS = {
    2: {"market_cap_floor": 2_000_000_000, "min_avg_volume": 500_000},
    3: {"market_cap_floor": 300_000_000, "min_avg_volume": 100_000},
}
MAX_SYMBOLS_PER_SECTOR = 3


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
    if market_cap < TIER_GUARDRAILS[tier]["market_cap_floor"]:
        raise GuardrailViolation(
            f"market cap {market_cap} below tier {tier} floor "
            f"{TIER_GUARDRAILS[tier]['market_cap_floor']}"
        )
    avg_volume = fetch_avg_volume(data_client, symbol)
    existing_sector_counts = sector_counts_for_tier(tier, symbol_tier=symbol_tier, sector_map=sector_map)
    check_guardrail(tier, market_cap, avg_volume, sector, existing_sector_counts)
