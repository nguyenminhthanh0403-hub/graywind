#!/usr/bin/env python3
"""Fetches historical 15-minute bars for a handful of sector-proxy ETFs
(energy/tech/health) into data/sector/, for the one-off backtest comparing
whether Graywind's RSI+SMA thresholds behave the same across sectors.

Deliberately separate from fetch_alpaca_data.py's WATCHLIST (["AAPL", "SPY"])
and OUTPUT_DIR ("alpaca_data") -- this is a backtest-only research run, not a
change to what the live loop trades. Requires ALPACA_API_KEY /
ALPACA_API_SECRET in the environment.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alpaca.data.historical import StockHistoricalDataClient

from fetch_alpaca_data import fetch_bars, write_csv

SECTOR_SYMBOLS = ["XLE", "XLK", "XLV"]  # energy, technology, health care
OUTPUT_DIR = "data/sector"


def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY / ALPACA_API_SECRET not set", file=sys.stderr)
        sys.exit(1)

    client = StockHistoricalDataClient(api_key, api_secret)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)

    for symbol in SECTOR_SYMBOLS:
        try:
            bars = fetch_bars(client, symbol, start, end)
            path = write_csv(symbol, bars, output_dir=OUTPUT_DIR)
            print(f"wrote {len(bars)} bars for {symbol} to {path}")
        except Exception as exc:
            print(f"ERROR fetching {symbol}: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
