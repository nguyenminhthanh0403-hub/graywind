#!/usr/bin/env python3
"""Fetches historical 15-minute bars for Graywind's Phase 1 watchlist
(AAPL, SPY) from Alpaca and writes them to local CSVs for the backtester
and strategy engine to load. Requires ALPACA_API_KEY / ALPACA_API_SECRET
in the environment.
"""
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

WATCHLIST = ["AAPL", "SPY"]
OUTPUT_DIR = "alpaca_data"


def fetch_bars(client, symbol, start, end):
    request = StockBarsRequest(
        symbol_or_symbols=[symbol],
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        start=start,
        end=end,
        # A free/paper account can't query the default SIP feed for recent
        # data ("subscription does not permit querying recent SIP data") --
        # IEX is the feed free-tier accounts are actually allowed to use.
        feed=DataFeed.IEX,
    )
    response = client.get_stock_bars(request)
    return list(response[symbol])


def write_csv(symbol, bars, output_dir=OUTPUT_DIR):
    if not bars:
        raise ValueError(f"no bars returned for {symbol}, refusing to write an empty/stale CSV")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{symbol.lower()}.csv")
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        for bar in bars:
            writer.writerow([
                bar.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                bar.open, bar.high, bar.low, bar.close, bar.volume,
            ])
    return path


def main():
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        print("ERROR: ALPACA_API_KEY / ALPACA_API_SECRET not set", file=sys.stderr)
        sys.exit(1)

    client = StockHistoricalDataClient(api_key, api_secret)
    # tz-aware, not datetime.utcnow() (deprecated in Python 3.12+ and
    # returns a naive datetime) -- live_loop.py passes tz-aware ET
    # datetimes into this module's fetch_bars(), so this stays consistent
    # with that rather than leaving a latent naive/aware inconsistency.
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=180)

    for symbol in WATCHLIST:
        try:
            bars = fetch_bars(client, symbol, start, end)
            path = write_csv(symbol, bars)
            print(f"wrote {len(bars)} bars for {symbol} to {path}")
        except Exception as exc:
            print(f"ERROR fetching {symbol}: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
