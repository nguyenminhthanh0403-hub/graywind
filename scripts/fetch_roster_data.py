#!/usr/bin/env python3
"""Fetches historical 15-minute bars for the sector-engine roster expansion
(energy: XOM/CVX, tech: NVDA/MSFT, health: JNJ/UNH -- see
docs/superpowers/specs/2026-08-17-graywind-sector-engine-design.md) into
data/roster/, for backtesting and out-of-sample validation.

Deliberately separate from fetch_alpaca_data.py's WATCHLIST (["AAPL", "SPY"])
and live_loop.py's WATCHLIST -- per the design's resolved sequencing, these
symbols reach the live paper-trading watchlist only after they're
backtest-validated, not in the same change that fetches their data.
Requires ALPACA_API_KEY / ALPACA_API_SECRET in the environment.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.historical import StockHistoricalDataClient

from fetch_alpaca_data import fetch_bars, write_csv

ROSTER_SYMBOLS = ["XOM", "CVX", "NVDA", "MSFT", "JNJ", "UNH"]
OUTPUT_DIR = "data/roster"


def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY / ALPACA_API_SECRET not set", file=sys.stderr)
        sys.exit(1)

    client = StockHistoricalDataClient(api_key, api_secret)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)

    for symbol in ROSTER_SYMBOLS:
        try:
            bars = fetch_bars(client, symbol, start, end)
            path = write_csv(symbol, bars, output_dir=OUTPUT_DIR)
            print(f"wrote {len(bars)} bars for {symbol} to {path}")
        except Exception as exc:
            print(f"ERROR fetching {symbol}: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
