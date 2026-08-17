#!/usr/bin/env python3
"""Out-of-sample validation for the sector-aware confirmation-bars engine
(docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md).

Splits each symbol's CSV chronologically -- the last 20% of bars held out
-- and re-runs the hold-time whipsaw breakdown from the original
root-cause analysis (see the spec's "Root cause" section) *only on trades
opened in that held-out window*, comparing short-hold-bucket win rate with
confirmation-bars on vs. off. This is what proves the fix generalizes,
rather than just fitting the data already eyeballed during root-cause
analysis.

The backtest itself runs against each symbol's FULL history, not a
truncated slice -- volatility.confirmation_bars_series needs real trailing
history (up to 260 bars) to leave its K=1 fallback, and truncating the
input df to just the held-out 20% would starve it of that. Only the
*scoring* (which round trips count toward the printed win rates) is
restricted to the held-out window, via each round trip's entry (buy) time.

Requires data/roster/*.csv (scripts/fetch_roster_data.py) and
data/sector/*.csv / alpaca_data/*.csv (scripts/fetch_sector_data.py /
fetch_alpaca_data.py) already fetched -- symbols whose CSV doesn't exist
yet are skipped with a note, not treated as an error.

Run with: python3 scripts/validate_sector_engine.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from graywind_strategy.backtester import run_backtest

HOLDOUT_FRACTION = 0.2

SYMBOLS = {
    "AAPL": "alpaca_data/aapl.csv",
    "SPY": "alpaca_data/spy.csv",
    "XLE": "data/sector/xle.csv",
    "XLK": "data/sector/xlk.csv",
    "XLV": "data/sector/xlv.csv",
    "XOM": "data/roster/xom.csv",
    "CVX": "data/roster/cvx.csv",
    "NVDA": "data/roster/nvda.csv",
    "MSFT": "data/roster/msft.csv",
    "JNJ": "data/roster/jnj.csv",
    "UNH": "data/roster/unh.csv",
}


def held_out_cutoff_time(df, holdout_fraction=HOLDOUT_FRACTION):
    split_index = int(len(df) * (1 - holdout_fraction))
    return df["time"].iloc[split_index]


def hold_time_bucket_win_rates(trades, entries_at_or_after):
    """Pairs buy/sell round trips (same technique as
    graywind_strategy.backtester.win_rate), keeping only round trips whose
    entry (buy) time is at or after `entries_at_or_after`, then splits
    those into <1 day hold vs >=1 day hold buckets. Returns
    (short_hold_win_rate_or_None, short_hold_count,
     long_hold_win_rate_or_None, long_hold_count).
    """
    round_trips = []
    open_by_symbol = {}
    for trade in trades:
        symbol = trade["symbol"]
        if trade["action"] == "buy":
            open_by_symbol[symbol] = trade
        elif trade["action"] == "sell":
            opened = open_by_symbol.pop(symbol, None)
            if opened is not None and opened["time"] >= entries_at_or_after:
                hold_time = trade["time"] - opened["time"]
                round_trips.append((hold_time, trade["price"] > opened["price"]))

    short = [win for hold_time, win in round_trips if hold_time.total_seconds() < 86400]
    long = [win for hold_time, win in round_trips if hold_time.total_seconds() >= 86400]

    short_win_rate = sum(short) / len(short) if short else None
    long_win_rate = sum(long) / len(long) if long else None
    return short_win_rate, len(short), long_win_rate, len(long)


def format_rate(rate):
    return f"{rate:.1%}" if rate is not None else "n/a"


def main():
    print(f"{'symbol':<8}{'filter':<8}{'short_n':>9}{'short_win':>11}{'long_n':>9}{'long_win':>11}")
    for symbol, path in SYMBOLS.items():
        try:
            df = pd.read_csv(path, parse_dates=["time"])
        except FileNotFoundError:
            print(f"{symbol:<8}SKIPPED (no CSV at {path} -- run the matching fetch script first)")
            continue

        cutoff = held_out_cutoff_time(df)

        for label, override in (("off", {symbol: None}), ("on", None)):
            result = run_backtest(
                {symbol: df}, starting_equity=10000.0, gates_always_pass=True,
                confirmation_bars_override=override,
            )
            short_win, short_n, long_win, long_n = hold_time_bucket_win_rates(result.trades, cutoff)
            print(
                f"{symbol:<8}{label:<8}{short_n:>9}{format_rate(short_win):>11}"
                f"{long_n:>9}{format_rate(long_win):>11}"
            )


if __name__ == "__main__":
    main()
