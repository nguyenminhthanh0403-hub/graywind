"""Task 11 Step 5 integration-verification script: real end-to-end
run_backtest() call against synthetic OHLCV data.

This environment has no real ALPACA_API_KEY/ALPACA_API_SECRET, so
fetch_alpaca_data.py could not be run against the real Alpaca API, and no
real FRED_API_KEY/FINNHUB_API_KEY or a real news_client for the
vix/sentiment/earnings gates. Per the task-11 dispatch instructions, this
script generates synthetic, oscillating (non-monotonic -- per the Task 6
review finding that a pure ramp fixture can hide real bugs), multi-day
15-minute OHLCV bars for AAPL and SPY spanning a weekend, and passes
run_backtest(..., gates_always_pass=True) to bypass the vix/sentiment/
earnings gates for this one verification run, pending real keys (see
Task 12).

Kept as a committed, reproducible script (not a deleted throwaway) per
review feedback on the first two rounds of this task -- the exact
integration numbers in task-11-report.md must be independently
reproducible by re-running this file, not just trusted from a report.

Run with: ./.venv/bin/python scripts/task11_integration_run.py
(no PYTHONPATH= prefix needed -- this script bootstraps its own sys.path
below so it works regardless of the caller's cwd or PYTHONPATH.)
"""
import math
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from graywind_strategy.backtester import run_backtest

random.seed(42)


def synthetic_bars(base_price, days_offset_list, amplitude_frac=0.03, period_bars=18):
    """15-minute bars, 9:30-15:45 ET (naive, matches fetch_alpaca_data.py's
    '%Y-%m-%d %H:%M:%S' format with no tz column), across several trading
    days that span a weekend. Prices oscillate via a sine wave + noise --
    explicitly non-monotonic per the Task 6 review finding that a pure ramp
    fixture can hide real bugs.
    """
    rows = []
    bar_index = 0
    for day in days_offset_list:
        day_start = datetime(2024, 1, 1) + timedelta(days=day)
        t = day_start.replace(hour=9, minute=30, second=0)
        end_t = day_start.replace(hour=15, minute=45, second=0)
        while t <= end_t:
            oscillation = amplitude_frac * math.sin(2 * math.pi * bar_index / period_bars)
            noise = random.uniform(-0.003, 0.003)
            close = round(base_price * (1 + oscillation + noise), 2)
            spread = round(close * 0.0015, 2)
            open_ = round(close - spread * random.uniform(-1, 1), 2)
            high = round(max(open_, close) + spread, 2)
            low = round(min(open_, close) - spread, 2)
            volume = random.randint(50_000, 500_000)
            rows.append({
                "time": t.strftime("%Y-%m-%d %H:%M:%S"),
                "open": open_, "high": high, "low": low, "close": close,
                "volume": volume,
            })
            t += timedelta(minutes=15)
            bar_index += 1
    return rows


# 2024-01-01 is a Monday. Offsets 1-5 = Tue-Fri (Jan 2-5), then 8-12 =
# Mon-Fri of the following week (Jan 8-12) -- spans one full weekend, 9
# trading days total (>> the PDT throttle's 5-business-day window), 26
# bars/day = 260 bars per symbol, far past the 30-bar indicator warmup.
trading_day_offsets = [1, 2, 3, 4, 5, 8, 9, 10, 11, 12]

aapl_rows = synthetic_bars(base_price=150.0, days_offset_list=trading_day_offsets, period_bars=18)
spy_rows = synthetic_bars(base_price=470.0, days_offset_list=trading_day_offsets, period_bars=13)

df_by_symbol = {
    "AAPL": pd.DataFrame(aapl_rows).assign(time=lambda d: pd.to_datetime(d["time"])),
    "SPY": pd.DataFrame(spy_rows).assign(time=lambda d: pd.to_datetime(d["time"])),
}

print(f"AAPL bars: {len(df_by_symbol['AAPL'])}, spans "
      f"{df_by_symbol['AAPL']['time'].min()} to {df_by_symbol['AAPL']['time'].max()}")
print(f"SPY bars: {len(df_by_symbol['SPY'])}, spans "
      f"{df_by_symbol['SPY']['time'].min()} to {df_by_symbol['SPY']['time'].max()}")

result = run_backtest(df_by_symbol, starting_equity=10000.0,
                       fred_api_key=None, news_client=None, finnhub_api_key=None,
                       gates_always_pass=True)

print(f"trades={len(result.trades)} sharpe={result.sharpe:.3f} "
      f"max_drawdown={result.max_drawdown:.3f} win_rate={result.win_rate:.3f} "
      f"pdt_compliant={result.pdt_compliant}")

buy_count = sum(1 for t in result.trades if t["action"] == "buy")
sell_count = sum(1 for t in result.trades if t["action"] == "sell")
print(f"buys={buy_count} sells={sell_count} "
      f"equity_curve_points={len(result.equity_curve)} "
      f"final_equity={result.equity_curve[-1]:.2f} starting_equity=10000.00")
print(f"first 5 trades: {result.trades[:5]}")
print(f"last 5 trades: {result.trades[-5:]}")
