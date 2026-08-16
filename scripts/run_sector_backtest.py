#!/usr/bin/env python3
"""One-off research script: runs the (now lookahead/capital/drawdown-fixed)
backtester independently on each of five symbols -- the current live
watchlist (AAPL, SPY) plus three single-sector ETF proxies (XLE energy,
XLK tech, XLV health) -- to see whether Graywind's fixed RSI(14)+SMA(10/30)
thresholds behave differently across sectors with different volatility
regimes.

Each symbol gets its own fresh $10,000 starting equity (run independently,
not pooled) so the comparison is apples-to-apples per symbol, not a
shared-capital portfolio run. gates_always_pass=True because this machine
has no FRED_API_KEY/FINNHUB_API_KEY/news_client to evaluate the
vix/sentiment/earnings gates -- same bypass task11_integration_run.py uses.

Run with: python3 scripts/run_sector_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from graywind_strategy.backtester import run_backtest

SYMBOLS = {
    "AAPL": "alpaca_data/aapl.csv",
    "SPY": "alpaca_data/spy.csv",
    "XLE": "data/sector/xle.csv",
    "XLK": "data/sector/xlk.csv",
    "XLV": "data/sector/xlv.csv",
}


def main():
    print(f"{'symbol':<8}{'bars':>8}{'trades':>8}{'sharpe':>10}{'max_dd':>10}{'win_rate':>10}")
    for symbol, path in SYMBOLS.items():
        df = pd.read_csv(path, parse_dates=["time"])
        result = run_backtest({symbol: df}, starting_equity=10000.0, gates_always_pass=True)
        print(
            f"{symbol:<8}{len(df):>8}{len(result.trades):>8}"
            f"{result.sharpe:>10.3f}{result.max_drawdown:>10.3%}{result.win_rate:>10.3%}"
        )


if __name__ == "__main__":
    main()
