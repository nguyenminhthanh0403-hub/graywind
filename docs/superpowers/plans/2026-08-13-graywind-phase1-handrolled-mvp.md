# Graywind Phase 1 Hand-Rolled MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working, backtestable, PDT-compliant rule-based intraday equities
trading pipeline (data → RSI/MA-crossover signal → volatility/sentiment/earnings gates →
risk-checked order → paper fill → backtest/live evaluation) on plain `pandas` + `alpaca-py`,
proving the pipeline end-to-end before any ML or real capital.

**Architecture:** A flat `graywind_strategy/` package holds pure-Python, independently
unit-testable modules: three risk-management classes (unchanged from the original LEAN-era
design), a `strategy_engine` module computing RSI+MA-crossover signals on a pandas
DataFrame via `pandas-ta-classic`, three `gates/` modules (VIX/FRED, sentiment/Alpaca
News+VADER, earnings/Finnhub) that each fail closed on data-source failure, a `pipeline`
module that composes signal → gates → risk into one `decide_trade()` call, and a
hand-rolled `backtester` module that replays that same `decide_trade()` bar-by-bar over
historical data. Two root-level scripts bookend the package: `fetch_alpaca_data.py`
(research-path data ingestion, run manually) and `live_loop.py` (a single-shot script
meant to be invoked every 15 minutes by an external scheduler during market hours — same
cron-driven shape as the Bullion project's data pipeline, not a long-running process).

**Tech Stack:** Python 3.11+, `pandas`, `pandas-ta-classic`, `alpaca-py`, `vaderSentiment`,
`requests`, `pytest`. No Docker, no `lean-cli`.

## Global Constraints

- Asset class: US equities only — fixed two-symbol watchlist (AAPL, SPY). No other
  symbols in Phase 1.
- Framework: no third-party trading engine. Hand-rolled on `pandas` + `alpaca-py`. $0 cost.
- Timeframe: 15-minute bars only (not 5-minute, not daily).
- Capital assumption: under $25k → PDT rule is a hard constraint: max 3 day-trades
  (opened + closed same session) per rolling 5 business days.
- Broker/data: Alpaca — free paper trading + free historical/live bars via the IEX feed,
  plus Alpaca's free News API for the sentiment gate. New free accounts required: FRED
  (instant key) and Finnhub (instant key, no card).
- Risk: fixed-fractional position sizing at 1% of account equity risked per trade;
  per-trade stop-loss 2% / take-profit 3%; daily drawdown circuit breaker at 2% of
  starting-of-day equity. These are Phase 1 starting defaults, not tuned — revisit once
  backtest results (Task 11) give a real basis to adjust them.
- New in this pivot — Signal Augmentation Gates: VIX gate (block if yesterday's FRED
  `VIXCLS` close ≥ 25.0), sentiment gate (block if VADER compound score on recent Alpaca
  News headlines < -0.2), earnings gate (block if earnings date is within 3 calendar days).
  All three thresholds are Phase 1 starting defaults, same status as the risk numbers
  above. **Fail-closed rule, non-negotiable**: if a gate's underlying data source is
  unreachable, that gate blocks the trade — it must never skip itself and let the signal
  through.
- Orders: market orders only. No limit orders, no partial-fill handling.
- Position sizing: fixed-fractional only. No Kelly Criterion.
- Trading hours: US equities regular session only (~9:30am–4:00pm ET, Mon–Fri, no
  holidays). No extended hours, no 24/7 operation.
- Strategy: rule-based only (RSI + moving-average crossover, same thresholds as the
  original LEAN-era design: RSI period 14, fast SMA 10, slow SMA 30, oversold 30,
  overbought 70). No ML/RL model.
- No real capital anywhere in this plan — paper trading only.
- Never commit real API keys/secrets (Alpaca, FRED, Finnhub). Read from environment
  variables only; `.gitignore` covers any local secret/state files.
- Before trusting any external API's exact response shape in code, confirm it with a real
  test call during implementation, not just documentation prose (this project's standing
  discipline — the LEAN-to-hand-rolled pivot itself came from doing exactly this).

---

### Task 1: Environment Setup + Package Scaffold

**Files:**
- Modify: `requirements.txt` (currently stale from the abandoned LEAN attempt —
  `lean`/`alpaca-py`/`pytest`)
- Modify: `.gitignore` (already has the needed entries from the abandoned attempt,
  uncommitted — verify and commit as-is)
- Create: `graywind_strategy/__init__.py`
- Create: `graywind_strategy/risk/__init__.py`
- Create: `graywind_strategy/gates/__init__.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the repo skeleton every later task builds inside — the `graywind_strategy/`
  package with `risk/` and `gates/` subpackages, and the Python environment `tests/`
  (Task 2+) and the root-level scripts (Tasks 5, 12) run inside.

- [ ] **Step 1: Overwrite `requirements.txt` with the hand-rolled package set**

```
pandas
pandas-ta-classic
alpaca-py
vaderSentiment
requests
pytest
```

- [ ] **Step 2: Verify `.gitignore` already covers the hand-rolled stack's local artifacts**

Run: `cat .gitignore`
Expected: contains `.worktrees/`, `data/`, `alpaca_data/`, `__pycache__/`, `*.pyc`,
`.venv/`, `venv/`, `.env`, `backtests/` (all already appended during the abandoned LEAN
attempt). Add one more line for this pivot's live-loop state file:

```
state/
```

- [ ] **Step 3: Verify Python is available**

Run: `python3 --version`
Expected: Python 3.11 or higher. (No Docker check needed — this stack has no Docker
dependency.)

- [ ] **Step 4: Install dependencies into the existing virtual environment**

Run:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```
Expected: `pandas`, `pandas-ta-classic`, `vaderSentiment`, and `requests` install without
error (`alpaca-py` and `pytest` are already installed from the abandoned attempt and will
just be confirmed present; `lean` stays installed but unused — harmless, not worth
uninstalling).

- [ ] **Step 5: Create the package skeleton**

Create `graywind_strategy/__init__.py` (empty file).
Create the `graywind_strategy/risk/` directory and `graywind_strategy/risk/__init__.py`
(empty file).
Create the `graywind_strategy/gates/` directory and `graywind_strategy/gates/__init__.py`
(empty file).

- [ ] **Step 6: Verify the scaffold**

Run: `ls graywind_strategy/__init__.py graywind_strategy/risk/__init__.py graywind_strategy/gates/__init__.py`
Expected: all three paths listed, no "No such file" errors.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore graywind_strategy/__init__.py graywind_strategy/risk/__init__.py graywind_strategy/gates/__init__.py
git commit -m "chore: scaffold hand-rolled package, drop LEAN from requirements"
```

---

### Task 2: PDT Day-Trade Throttle

**Files:**
- Create: `graywind_strategy/risk/pdt_throttle.py`
- Test: `tests/test_pdt_throttle.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PDTThrottle` class with `record_day_trade(trade_date: date) -> None` and
  `can_open_day_trade(as_of: date) -> bool`. Task 10 imports this as
  `from graywind_strategy.risk.pdt_throttle import PDTThrottle`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pdt_throttle.py`:

```python
from datetime import date

from graywind_strategy.risk.pdt_throttle import PDTThrottle


def test_can_open_day_trade_true_when_no_trades_recorded():
    throttle = PDTThrottle()
    assert throttle.can_open_day_trade(date(2024, 1, 8)) is True


def test_allows_up_to_three_day_trades_then_blocks_fourth():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))   # Mon
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    assert throttle.can_open_day_trade(date(2024, 1, 11)) is False  # Thu


def test_weekend_days_are_not_counted_in_the_five_business_day_window():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))   # Mon
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    # Jan 13-14 is a weekend; if weekends were miscounted as business days,
    # this would incorrectly read as True.
    assert throttle.can_open_day_trade(date(2024, 1, 15)) is False  # Mon


def test_oldest_day_trade_ages_out_of_the_five_business_day_window():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))   # Mon
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    assert throttle.can_open_day_trade(date(2024, 1, 16)) is True  # Tue, Jan 8 aged out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pdt_throttle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.risk.pdt_throttle'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/risk/pdt_throttle.py`:

```python
"""PDT (Pattern Day Trader) rolling-window day-trade throttle.

Enforces FINRA's rule for accounts under $25k: no more than 3 day-trades
(a position opened and closed within the same session) in any rolling
5-business-day window.
"""
from collections import deque
from datetime import date, timedelta


class PDTThrottle:
    MAX_DAY_TRADES = 3
    WINDOW_BUSINESS_DAYS = 5

    def __init__(self):
        self._day_trade_dates = deque()

    def record_day_trade(self, trade_date):
        self._day_trade_dates.append(trade_date)

    def can_open_day_trade(self, as_of):
        self._prune(as_of)
        return len(self._day_trade_dates) < self.MAX_DAY_TRADES

    def _prune(self, as_of):
        cutoff = self._business_days_ago(as_of, self.WINDOW_BUSINESS_DAYS)
        while self._day_trade_dates and self._day_trade_dates[0] < cutoff:
            self._day_trade_dates.popleft()

    @staticmethod
    def _business_days_ago(as_of, n):
        d = as_of
        counted = 0
        while counted < n:
            d -= timedelta(days=1)
            if d.weekday() < 5:  # Mon=0 .. Fri=4
                counted += 1
        return d
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pdt_throttle.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/risk/pdt_throttle.py tests/test_pdt_throttle.py
git commit -m "feat: add PDT rolling-window day-trade throttle"
```

---

### Task 3: Position Sizing & Stop-Loss/Take-Profit Calculator

**Files:**
- Create: `graywind_strategy/risk/position_sizing.py`
- Test: `tests/test_position_sizing.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PositionSizer` class with `__init__(self, risk_fraction: float = 0.01)`,
  `shares_to_buy(account_equity: float, entry_price: float, stop_price: float) -> int`,
  static `stop_loss_price(entry_price: float, stop_pct: float) -> float`, static
  `take_profit_price(entry_price: float, take_profit_pct: float) -> float`. Task 10
  imports this as `from graywind_strategy.risk.position_sizing import PositionSizer`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_position_sizing.py`:

```python
import pytest

from graywind_strategy.risk.position_sizing import PositionSizer


def test_shares_to_buy_risks_exactly_the_configured_fraction_of_equity():
    sizer = PositionSizer(risk_fraction=0.01)
    shares = sizer.shares_to_buy(account_equity=10000, entry_price=50, stop_price=49)
    assert shares == 100  # $100 at risk / $1 risk-per-share


def test_shares_to_buy_rounds_down_to_whole_shares():
    sizer = PositionSizer(risk_fraction=0.01)
    shares = sizer.shares_to_buy(account_equity=10000, entry_price=50, stop_price=49.7)
    assert shares == 333  # $100 / $0.30 = 333.33 -> floor to 333


def test_shares_to_buy_raises_when_stop_not_below_entry():
    sizer = PositionSizer(risk_fraction=0.01)
    with pytest.raises(ValueError):
        sizer.shares_to_buy(account_equity=10000, entry_price=50, stop_price=50)


def test_init_raises_on_invalid_risk_fraction():
    with pytest.raises(ValueError):
        PositionSizer(risk_fraction=1.5)


def test_stop_loss_price():
    assert PositionSizer.stop_loss_price(entry_price=100, stop_pct=0.02) == 98.0


def test_take_profit_price():
    assert PositionSizer.take_profit_price(entry_price=100, take_profit_pct=0.03) == 103.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_position_sizing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.risk.position_sizing'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/risk/position_sizing.py`:

```python
"""Fixed-fractional position sizing: risk a fixed percentage of account
equity per trade, sized off the distance to the stop-loss.
"""


class PositionSizer:
    def __init__(self, risk_fraction=0.01):
        if not 0 < risk_fraction < 1:
            raise ValueError("risk_fraction must be between 0 and 1")
        self.risk_fraction = risk_fraction

    def shares_to_buy(self, account_equity, entry_price, stop_price):
        if stop_price >= entry_price:
            raise ValueError("stop_price must be below entry_price for a long position")
        risk_per_share = entry_price - stop_price
        dollars_at_risk = account_equity * self.risk_fraction
        return int(dollars_at_risk // risk_per_share)

    @staticmethod
    def stop_loss_price(entry_price, stop_pct):
        return round(entry_price * (1 - stop_pct), 2)

    @staticmethod
    def take_profit_price(entry_price, take_profit_pct):
        return round(entry_price * (1 + take_profit_pct), 2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_position_sizing.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/risk/position_sizing.py tests/test_position_sizing.py
git commit -m "feat: add fixed-fractional position sizing and stop/take-profit calculator"
```

---

### Task 4: Daily Drawdown Circuit Breaker

**Files:**
- Create: `graywind_strategy/risk/drawdown_breaker.py`
- Test: `tests/test_drawdown_breaker.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DrawdownBreaker` class with `__init__(self, max_daily_loss_fraction: float = 0.02)`,
  `start_new_day(day: date, starting_equity: float) -> None`,
  `update_equity(current_equity: float) -> None`, `can_open_new_trade() -> bool`. Task 10
  imports this as `from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_drawdown_breaker.py`:

```python
from datetime import date

import pytest

from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker


def test_allows_trading_before_any_loss():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    assert breaker.can_open_new_trade() is True


def test_trips_at_exactly_the_configured_loss_threshold():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    breaker.update_equity(9800)  # exactly -2%
    assert breaker.can_open_new_trade() is False


def test_does_not_trip_under_threshold():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    breaker.update_equity(9801)  # -1.99%
    assert breaker.can_open_new_trade() is True


def test_new_day_resets_the_breaker():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    breaker.update_equity(9800)
    assert breaker.can_open_new_trade() is False
    breaker.start_new_day(date(2024, 1, 9), starting_equity=9800)
    assert breaker.can_open_new_trade() is True


def test_init_raises_on_invalid_fraction():
    with pytest.raises(ValueError):
        DrawdownBreaker(max_daily_loss_fraction=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_drawdown_breaker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.risk.drawdown_breaker'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/risk/drawdown_breaker.py`:

```python
"""Daily drawdown circuit breaker: halts new trades for the rest of the day
once realized+unrealized losses reach a configured fraction of
starting-of-day account equity.
"""


class DrawdownBreaker:
    def __init__(self, max_daily_loss_fraction=0.02):
        if not 0 < max_daily_loss_fraction < 1:
            raise ValueError("max_daily_loss_fraction must be between 0 and 1")
        self.max_daily_loss_fraction = max_daily_loss_fraction
        self._current_day = None
        self._start_of_day_equity = 0.0
        self._tripped = False

    def start_new_day(self, day, starting_equity):
        self._current_day = day
        self._start_of_day_equity = starting_equity
        self._tripped = False

    def update_equity(self, current_equity):
        loss_fraction = (self._start_of_day_equity - current_equity) / self._start_of_day_equity
        if loss_fraction >= self.max_daily_loss_fraction:
            self._tripped = True

    def can_open_new_trade(self):
        return not self._tripped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_drawdown_breaker.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/risk/drawdown_breaker.py tests/test_drawdown_breaker.py
git commit -m "feat: add daily drawdown circuit breaker"
```

---

### Task 5: Alpaca Historical Data Fetch Script

**Files:**
- Create: `fetch_alpaca_data.py`
- Test: `tests/test_fetch_alpaca_data.py`

**Interfaces:**
- Consumes: `ALPACA_API_KEY` / `ALPACA_API_SECRET` environment variables (real Alpaca
  paper-account credentials, set locally by the user — never committed).
- Produces: CSV files at `alpaca_data/<symbol_lowercased>.csv` with header
  `time,open,high,low,close,volume`, one row per 15-minute bar,
  `time` formatted `%Y-%m-%d %H:%M:%S`. Task 6's `strategy_engine` and Task 11's
  `backtester` load this exact format/path convention directly into pandas.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fetch_alpaca_data.py`:

```python
import csv
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fetch_alpaca_data import fetch_bars, write_csv


def make_bar(ts, o, h, l, c, v):
    return SimpleNamespace(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def test_write_csv_writes_header_and_rows(tmp_path):
    bars = [make_bar(datetime(2024, 1, 8, 9, 30), 100.0, 101.0, 99.5, 100.5, 1000)]
    path = write_csv("AAPL", bars, output_dir=str(tmp_path))
    with open(path) as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["time", "open", "high", "low", "close", "volume"]
    assert rows[1] == ["2024-01-08 09:30:00", "100.0", "101.0", "99.5", "100.5", "1000"]


def test_write_csv_raises_on_empty_bars_and_writes_nothing(tmp_path):
    with pytest.raises(ValueError):
        write_csv("AAPL", [], output_dir=str(tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_fetch_bars_calls_client_with_expected_symbol():
    fake_client = MagicMock()
    fake_client.get_stock_bars.return_value = {
        "AAPL": [make_bar(datetime(2024, 1, 8), 1, 2, 0.5, 1.5, 10)]
    }
    result = fetch_bars(fake_client, "AAPL", datetime(2024, 1, 1), datetime(2024, 1, 8))
    assert len(result) == 1
    fake_client.get_stock_bars.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_fetch_alpaca_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fetch_alpaca_data'`

- [ ] **Step 3: Write the implementation**

Create `fetch_alpaca_data.py`:

```python
#!/usr/bin/env python3
"""Fetches historical 15-minute bars for Graywind's Phase 1 watchlist
(AAPL, SPY) from Alpaca and writes them to local CSVs for the backtester
and strategy engine to load. Requires ALPACA_API_KEY / ALPACA_API_SECRET
in the environment.
"""
import csv
import os
import sys
from datetime import datetime, timedelta

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
    end = datetime.utcnow()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_fetch_alpaca_data.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add fetch_alpaca_data.py tests/test_fetch_alpaca_data.py
git commit -m "feat: add Alpaca historical-bar fetch script with fail-closed error handling"
```

---

### Task 6: Strategy Engine — RSI + MA Crossover via `pandas-ta-classic`

**Files:**
- Create: `graywind_strategy/strategy_engine.py`
- Test: `tests/test_strategy_engine.py`

**Interfaces:**
- Consumes: a pandas DataFrame with at least a `close` column (Task 5's CSV, loaded via
  `pandas.read_csv`).
- Produces: `evaluate_signal(rsi_value, fast_value, slow_value, rsi_oversold=30,
  rsi_overbought=70) -> str` (pure function, returns `"buy"`/`"sell"`/`"hold"`) and
  `compute_signals(df, rsi_period=14, fast_period=10, slow_period=30, rsi_oversold=30,
  rsi_overbought=70) -> pd.DataFrame` (adds `rsi`, `sma_fast`, `sma_slow`, `signal`
  columns). Task 10's `pipeline` and Task 11's `backtester` both import
  `from graywind_strategy.strategy_engine import evaluate_signal, compute_signals`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_strategy_engine.py`:

```python
import pandas as pd

from graywind_strategy.strategy_engine import compute_signals, evaluate_signal


def test_evaluate_signal_buy_when_fast_above_slow_and_not_overbought():
    assert evaluate_signal(rsi_value=50, fast_value=105, slow_value=100) == "buy"


def test_evaluate_signal_sell_when_fast_below_slow_and_not_oversold():
    assert evaluate_signal(rsi_value=50, fast_value=95, slow_value=100) == "sell"


def test_evaluate_signal_hold_when_overbought_blocks_a_buy():
    assert evaluate_signal(rsi_value=75, fast_value=105, slow_value=100) == "hold"


def test_evaluate_signal_hold_when_oversold_blocks_a_sell():
    assert evaluate_signal(rsi_value=25, fast_value=95, slow_value=100) == "hold"


def test_evaluate_signal_hold_on_missing_indicator_values():
    assert evaluate_signal(rsi_value=float("nan"), fast_value=105, slow_value=100) == "hold"


def test_compute_signals_adds_expected_columns_and_does_not_raise():
    # 40 bars of a simple uptrend is enough to warm up a 30-period SMA.
    df = pd.DataFrame({
        "close": [100 + i * 0.5 for i in range(40)],
    })
    result = compute_signals(df)
    assert list(result.columns) == ["close", "rsi", "sma_fast", "sma_slow", "signal"]
    # The last row has enough history for every indicator to be ready.
    assert result["signal"].iloc[-1] in {"buy", "sell", "hold"}
    assert not pd.isna(result["rsi"].iloc[-1])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategy_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.strategy_engine'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/strategy_engine.py`:

```python
"""Rule-based RSI + moving-average crossover signal, computed on a plain
pandas DataFrame via pandas-ta-classic. Same thresholds as the original
LEAN-era design: RSI period 14, fast SMA 10, slow SMA 30, oversold 30,
overbought 70.
"""
import math

import pandas as pd
import pandas_ta_classic  # noqa: F401  (registers the .ta accessor on DataFrame)

RSI_PERIOD = 14
FAST_SMA_PERIOD = 10
SLOW_SMA_PERIOD = 30
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


def evaluate_signal(rsi_value, fast_value, slow_value,
                     rsi_oversold=RSI_OVERSOLD, rsi_overbought=RSI_OVERBOUGHT):
    if any(v is None or (isinstance(v, float) and math.isnan(v))
           for v in (rsi_value, fast_value, slow_value)):
        return "hold"
    if fast_value > slow_value and rsi_value < rsi_overbought:
        return "buy"
    if fast_value < slow_value and rsi_value > rsi_oversold:
        return "sell"
    return "hold"


def compute_signals(df, rsi_period=RSI_PERIOD, fast_period=FAST_SMA_PERIOD,
                     slow_period=SLOW_SMA_PERIOD, rsi_oversold=RSI_OVERSOLD,
                     rsi_overbought=RSI_OVERBOUGHT):
    df = df.copy()
    df["rsi"] = df.ta.rsi(length=rsi_period)
    df["sma_fast"] = df.ta.sma(length=fast_period)
    df["sma_slow"] = df.ta.sma(length=slow_period)
    df["signal"] = df.apply(
        lambda row: evaluate_signal(
            row["rsi"], row["sma_fast"], row["sma_slow"], rsi_oversold, rsi_overbought
        ),
        axis=1,
    )
    return df
```

Verification note for whoever implements this: `pandas-ta-classic` is a fork of
`pandas-ta` and is expected to expose the same `.ta` DataFrame accessor
(`df.ta.rsi(length=...)`, `df.ta.sma(length=...)`) — confirm this against the installed
package's actual API (`python -c "import pandas as pd, pandas_ta_classic; print(pd.DataFrame({'close':[1,2,3]*10}).ta.rsi(length=14))"`)
before trusting the import/accessor pattern above; adjust the import or accessor calls if
the real package differs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategy_engine.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/strategy_engine.py tests/test_strategy_engine.py
git commit -m "feat: add RSI+MA-crossover strategy engine via pandas-ta-classic"
```

---

### Task 7: VIX Circuit-Breaker Gate (FRED)

**Files:**
- Create: `graywind_strategy/gates/vix_gate.py`
- Test: `tests/test_vix_gate.py`

**Interfaces:**
- Consumes: `FRED_API_KEY` environment variable (free, instant key from
  fred.stlouisfed.org).
- Produces: `fetch_latest_vix(api_key, session=requests) -> float` (raises
  `VixDataUnavailable` on any failure) and `vix_gate(vix_value, threshold=25.0) -> bool`
  (pure). Task 10's `pipeline` imports both as
  `from graywind_strategy.gates.vix_gate import fetch_latest_vix, vix_gate, VixDataUnavailable`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vix_gate.py`:

```python
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.vix_gate import VixDataUnavailable, fetch_latest_vix, vix_gate


def test_vix_gate_allows_when_below_threshold():
    assert vix_gate(vix_value=18.0, threshold=25.0) is True


def test_vix_gate_blocks_when_at_or_above_threshold():
    assert vix_gate(vix_value=25.0, threshold=25.0) is False
    assert vix_gate(vix_value=30.0, threshold=25.0) is False


def test_fetch_latest_vix_parses_the_most_recent_observation():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "observations": [{"date": "2026-08-12", "value": "17.65"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    value = fetch_latest_vix("fake-key", session=fake_session)

    assert value == 17.65


def test_fetch_latest_vix_raises_on_http_error():
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network error")
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session)


def test_fetch_latest_vix_raises_on_missing_value_marker():
    # FRED returns "." for a series with no observation on a given day
    # (e.g. a market holiday) — must not be parsed as a float silently.
    fake_response = MagicMock()
    fake_response.json.return_value = {"observations": [{"date": "2026-08-12", "value": "."}]}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vix_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.gates.vix_gate'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/gates/vix_gate.py`:

```python
"""VIX circuit-breaker gate: blocks new trades when FRED's VIXCLS daily
close is at or above a configured threshold. Fails closed — any fetch or
parse failure raises VixDataUnavailable, which the caller (pipeline.py)
must treat as a blocked trade, never as a skipped gate.
"""
import requests

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
VIX_THRESHOLD = 25.0


class VixDataUnavailable(Exception):
    pass


def fetch_latest_vix(api_key, session=requests):
    params = {
        "series_id": "VIXCLS",
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    try:
        response = session.get(FRED_OBSERVATIONS_URL, params=params, timeout=10)
        response.raise_for_status()
        observations = response.json()["observations"]
        raw_value = observations[0]["value"]
        if raw_value == ".":
            raise VixDataUnavailable("FRED returned no observation for the latest date")
        return float(raw_value)
    except VixDataUnavailable:
        raise
    except Exception as exc:
        raise VixDataUnavailable(str(exc)) from exc


def vix_gate(vix_value, threshold=VIX_THRESHOLD):
    return vix_value < threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vix_gate.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/vix_gate.py tests/test_vix_gate.py
git commit -m "feat: add fail-closed VIX circuit-breaker gate via FRED"
```

---

### Task 8: Sentiment Gate (Alpaca News + VADER)

**Files:**
- Create: `graywind_strategy/gates/sentiment_gate.py`
- Test: `tests/test_sentiment_gate.py`

**Interfaces:**
- Consumes: an `alpaca.data.historical.news.NewsClient` instance (constructed by the
  caller from `ALPACA_API_KEY`/`ALPACA_API_SECRET`, same credentials Task 5 already uses).
- Produces: `fetch_recent_headlines(news_client, symbol, limit=10) -> list[str]` (raises
  `SentimentDataUnavailable` on fetch failure), `sentiment_score(headlines: list[str]) ->
  float` (pure — returns `0.0`, i.e. neutral, for an empty/no-news list; that is a
  successful "no news" result, not a failure), and `sentiment_gate(score, threshold=-0.2)
  -> bool` (pure). Task 10's `pipeline` imports all three as
  `from graywind_strategy.gates.sentiment_gate import fetch_recent_headlines, sentiment_score, sentiment_gate, SentimentDataUnavailable`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sentiment_gate.py`:

```python
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.sentiment_gate import (
    SentimentDataUnavailable,
    fetch_recent_headlines,
    sentiment_gate,
    sentiment_score,
)


def test_sentiment_score_of_empty_headlines_is_neutral():
    assert sentiment_score([]) == 0.0


def test_sentiment_score_positive_headlines_scores_above_zero():
    score = sentiment_score(["Company beats earnings expectations by a wide margin"])
    assert score > 0.0


def test_sentiment_score_negative_headlines_scores_below_zero():
    score = sentiment_score(["Company misses on revenue, shares plunge on fraud investigation"])
    assert score < 0.0


def test_sentiment_gate_allows_above_threshold():
    assert sentiment_gate(score=0.0, threshold=-0.2) is True


def test_sentiment_gate_blocks_below_threshold():
    assert sentiment_gate(score=-0.5, threshold=-0.2) is False


def test_fetch_recent_headlines_extracts_headline_field():
    fake_article = MagicMock()
    fake_article.headline = "Some Headline"
    fake_response = MagicMock()
    fake_response.data = {"news": [fake_article]}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response

    headlines = fetch_recent_headlines(fake_client, "AAPL", limit=5)

    assert headlines == ["Some Headline"]
    fake_client.get_news.assert_called_once()


def test_fetch_recent_headlines_raises_on_client_error():
    fake_client = MagicMock()
    fake_client.get_news.side_effect = Exception("network error")
    with pytest.raises(SentimentDataUnavailable):
        fetch_recent_headlines(fake_client, "AAPL")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.gates.sentiment_gate'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/gates/sentiment_gate.py`:

```python
"""Sentiment gate: blocks new trades when VADER's compound sentiment score
on recent Alpaca News headlines falls below a configured threshold. Fails
closed on fetch failure (SentimentDataUnavailable); a successful fetch that
finds no headlines is scored neutral (0.0), not treated as a failure.
"""
from alpaca.data.requests import NewsRequest
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

SENTIMENT_THRESHOLD = -0.2
_analyzer = SentimentIntensityAnalyzer()


class SentimentDataUnavailable(Exception):
    pass


def fetch_recent_headlines(news_client, symbol, limit=10):
    try:
        request = NewsRequest(symbol_or_symbols=symbol, limit=limit)
        response = news_client.get_news(request)
        return [article.headline for article in response.data["news"]]
    except Exception as exc:
        raise SentimentDataUnavailable(str(exc)) from exc


def sentiment_score(headlines):
    if not headlines:
        return 0.0
    scores = [_analyzer.polarity_scores(h)["compound"] for h in headlines]
    return sum(scores) / len(scores)


def sentiment_gate(score, threshold=SENTIMENT_THRESHOLD):
    return score >= threshold
```

Verification note for whoever implements this: confirm `alpaca.data.requests.NewsRequest`
and the `NewsClient.get_news(...).data["news"]` response shape against the installed
`alpaca-py` version with one real API call before trusting `fetch_recent_headlines`'s
parsing — the class/attribute names above are this plan's best-effort based on `alpaca-py`
documentation, not yet confirmed with a live call from inside this repo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sentiment_gate.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/sentiment_gate.py tests/test_sentiment_gate.py
git commit -m "feat: add fail-closed sentiment gate via Alpaca News + local VADER"
```

---

### Task 9: Earnings Blackout Gate (Finnhub)

**Files:**
- Create: `graywind_strategy/gates/earnings_gate.py`
- Test: `tests/test_earnings_gate.py`

**Interfaces:**
- Consumes: `FINNHUB_API_KEY` environment variable (free, instant key, no card, from
  finnhub.io).
- Produces: `fetch_next_earnings_date(symbol, api_key, as_of_date, session=requests) ->
  date | None` (raises `EarningsDataUnavailable` on fetch failure; returns `None` — not a
  failure — when the query window genuinely has no scheduled earnings) and
  `earnings_gate(next_earnings_date, as_of_date, blackout_days=3) -> bool` (pure). Task
  10's `pipeline` imports both as
  `from graywind_strategy.gates.earnings_gate import fetch_next_earnings_date, earnings_gate, EarningsDataUnavailable`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_earnings_gate.py`:

```python
from datetime import date
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.earnings_gate import (
    EarningsDataUnavailable,
    earnings_gate,
    fetch_next_earnings_date,
)


def test_earnings_gate_allows_when_no_earnings_scheduled():
    assert earnings_gate(next_earnings_date=None, as_of_date=date(2024, 1, 8)) is True


def test_earnings_gate_blocks_within_blackout_window():
    assert earnings_gate(
        next_earnings_date=date(2024, 1, 10), as_of_date=date(2024, 1, 8), blackout_days=3
    ) is False


def test_earnings_gate_allows_outside_blackout_window():
    assert earnings_gate(
        next_earnings_date=date(2024, 1, 20), as_of_date=date(2024, 1, 8), blackout_days=3
    ) is True


def test_earnings_gate_allows_when_earnings_date_already_passed():
    assert earnings_gate(
        next_earnings_date=date(2024, 1, 1), as_of_date=date(2024, 1, 8), blackout_days=3
    ) is True


def test_fetch_next_earnings_date_returns_earliest_date_in_window():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "earningsCalendar": [{"date": "2024-01-25"}, {"date": "2024-01-18"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = fetch_next_earnings_date("AAPL", "fake-key", date(2024, 1, 8), session=fake_session)

    assert result == date(2024, 1, 18)


def test_fetch_next_earnings_date_returns_none_when_calendar_is_empty():
    fake_response = MagicMock()
    fake_response.json.return_value = {"earningsCalendar": []}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = fetch_next_earnings_date("AAPL", "fake-key", date(2024, 1, 8), session=fake_session)

    assert result is None


def test_fetch_next_earnings_date_raises_on_http_error():
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network error")
    with pytest.raises(EarningsDataUnavailable):
        fetch_next_earnings_date("AAPL", "fake-key", date(2024, 1, 8), session=fake_session)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_earnings_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.gates.earnings_gate'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/gates/earnings_gate.py`:

```python
"""Earnings blackout gate: blocks new trades within a configured number of
calendar days before a scheduled earnings date. Fails closed on fetch
failure (EarningsDataUnavailable); a successful fetch that finds no
earnings in the queried window returns None, which the gate treats as
"allow", not "block" — no earnings scheduled is a legitimate, safe state.
"""
from datetime import date, timedelta

import requests

FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/earnings"
EARNINGS_LOOKAHEAD_DAYS = 30
EARNINGS_BLACKOUT_DAYS = 3


class EarningsDataUnavailable(Exception):
    pass


def fetch_next_earnings_date(symbol, api_key, as_of_date, session=requests):
    params = {
        "symbol": symbol,
        "from": as_of_date.isoformat(),
        "to": (as_of_date + timedelta(days=EARNINGS_LOOKAHEAD_DAYS)).isoformat(),
        "token": api_key,
    }
    try:
        response = session.get(FINNHUB_CALENDAR_URL, params=params, timeout=10)
        response.raise_for_status()
        entries = response.json().get("earningsCalendar", [])
        dates = [date.fromisoformat(entry["date"]) for entry in entries]
        return min(dates) if dates else None
    except Exception as exc:
        raise EarningsDataUnavailable(str(exc)) from exc


def earnings_gate(next_earnings_date, as_of_date, blackout_days=EARNINGS_BLACKOUT_DAYS):
    if next_earnings_date is None:
        return True
    days_until = (next_earnings_date - as_of_date).days
    return days_until < 0 or days_until > blackout_days
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_earnings_gate.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/gates/earnings_gate.py tests/test_earnings_gate.py
git commit -m "feat: add fail-closed earnings blackout gate via Finnhub"
```

---

### Task 10: Wire Gates + Risk Management Into a Single Trade-Decision Pipeline

**Files:**
- Create: `graywind_strategy/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `PDTThrottle` (Task 2), `PositionSizer` (Task 3), `DrawdownBreaker` (Task 4),
  `evaluate_signal` (Task 6), the three gates + their fetch functions (Tasks 7-9).
- Produces: `TradeDecision` (a small dataclass: `action: str` — `"buy"`, `"hold"`, or
  `"blocked"` — plus `reason: str` and, when `action == "buy"`, `shares: int`,
  `stop_price: float`, `target_price: float`) and `decide_trade(...)`. This is the single
  function both the backtester (Task 11) and the live loop (Task 12) call for every bar —
  it is the one place order-eligibility logic lives, so both paths behave identically.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
from datetime import date
from unittest.mock import patch

from graywind_strategy.gates.earnings_gate import EarningsDataUnavailable
from graywind_strategy.gates.sentiment_gate import SentimentDataUnavailable
from graywind_strategy.gates.vix_gate import VixDataUnavailable
from graywind_strategy.pipeline import (
    evaluate_earnings_gate,
    evaluate_sentiment_gate,
    evaluate_vix_gate,
    decide_trade,
)
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer


def test_evaluate_vix_gate_fails_closed_on_fetch_error():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", side_effect=VixDataUnavailable("boom")):
        assert evaluate_vix_gate(fred_api_key="k") is False


def test_evaluate_vix_gate_passes_through_on_success():
    with patch("graywind_strategy.pipeline.fetch_latest_vix", return_value=15.0):
        assert evaluate_vix_gate(fred_api_key="k") is True


def test_evaluate_sentiment_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_recent_headlines",
        side_effect=SentimentDataUnavailable("boom"),
    ):
        assert evaluate_sentiment_gate(news_client=object(), symbol="AAPL") is False


def test_evaluate_earnings_gate_fails_closed_on_fetch_error():
    with patch(
        "graywind_strategy.pipeline.fetch_next_earnings_date",
        side_effect=EarningsDataUnavailable("boom"),
    ):
        assert evaluate_earnings_gate(
            symbol="AAPL", finnhub_api_key="k", as_of_date=date(2024, 1, 8)
        ) is False


def _passing_gates():
    return patch.multiple(
        "graywind_strategy.pipeline",
        evaluate_vix_gate=lambda **kw: True,
        evaluate_sentiment_gate=lambda **kw: True,
        evaluate_earnings_gate=lambda **kw: True,
    )


def test_decide_trade_buys_when_signal_and_all_gates_and_risk_checks_pass():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "buy"
    assert decision.shares > 0
    assert decision.stop_price < 100.0
    assert decision.target_price > 100.0


def test_decide_trade_holds_on_non_buy_signal():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="hold",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "hold"


def test_decide_trade_blocks_when_drawdown_breaker_tripped():
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 8),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=PDTThrottle(),
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=False,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "drawdown_breaker"


def test_decide_trade_blocks_when_pdt_throttle_exhausted():
    throttle = PDTThrottle()
    for d in [date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)]:
        throttle.record_day_trade(d)
    with _passing_gates():
        decision = decide_trade(
            symbol="AAPL",
            signal="buy",
            as_of_date=date(2024, 1, 11),
            current_price=100.0,
            account_equity=10000.0,
            pdt_throttle=throttle,
            position_sizer=PositionSizer(risk_fraction=0.01),
            drawdown_breaker_ok=True,
            fred_api_key="k",
            news_client=object(),
            finnhub_api_key="k",
        )
    assert decision.action == "blocked"
    assert decision.reason == "pdt_throttle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.pipeline'`

- [ ] **Step 3: Write the implementation**

Create `graywind_strategy/pipeline.py`:

```python
"""Composes the strategy signal, the three signal-augmentation gates, and
risk management into one order-eligibility decision. This is the single
code path both the backtester and the live loop call — keeping order logic
in one place is what guarantees backtest and live behavior can't drift
apart.
"""
from dataclasses import dataclass
from typing import Optional

from graywind_strategy.gates.earnings_gate import (
    EARNINGS_BLACKOUT_DAYS,
    EarningsDataUnavailable,
    earnings_gate,
    fetch_next_earnings_date,
)
from graywind_strategy.gates.sentiment_gate import (
    SENTIMENT_THRESHOLD,
    SentimentDataUnavailable,
    fetch_recent_headlines,
    sentiment_gate,
    sentiment_score,
)
from graywind_strategy.gates.vix_gate import VIX_THRESHOLD, VixDataUnavailable, fetch_latest_vix, vix_gate


@dataclass
class TradeDecision:
    action: str  # "buy" | "hold" | "blocked"
    reason: str
    shares: Optional[int] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None


def evaluate_vix_gate(fred_api_key, threshold=VIX_THRESHOLD):
    try:
        vix_value = fetch_latest_vix(fred_api_key)
    except VixDataUnavailable:
        return False
    return vix_gate(vix_value, threshold)


def evaluate_sentiment_gate(news_client, symbol, threshold=SENTIMENT_THRESHOLD):
    try:
        headlines = fetch_recent_headlines(news_client, symbol)
    except SentimentDataUnavailable:
        return False
    return sentiment_gate(sentiment_score(headlines), threshold)


def evaluate_earnings_gate(symbol, finnhub_api_key, as_of_date, blackout_days=EARNINGS_BLACKOUT_DAYS):
    try:
        next_date = fetch_next_earnings_date(symbol, finnhub_api_key, as_of_date)
    except EarningsDataUnavailable:
        return False
    return earnings_gate(next_date, as_of_date, blackout_days)


def decide_trade(symbol, signal, as_of_date, current_price, account_equity,
                  pdt_throttle, position_sizer, drawdown_breaker_ok,
                  fred_api_key, news_client, finnhub_api_key,
                  stop_pct=0.02, take_profit_pct=0.03):
    if signal != "buy":
        return TradeDecision(action="hold", reason="no buy signal")

    if not evaluate_vix_gate(fred_api_key):
        return TradeDecision(action="blocked", reason="vix_gate")
    if not evaluate_sentiment_gate(news_client, symbol):
        return TradeDecision(action="blocked", reason="sentiment_gate")
    if not evaluate_earnings_gate(symbol, finnhub_api_key, as_of_date):
        return TradeDecision(action="blocked", reason="earnings_gate")

    if not drawdown_breaker_ok:
        return TradeDecision(action="blocked", reason="drawdown_breaker")
    if not pdt_throttle.can_open_day_trade(as_of_date):
        return TradeDecision(action="blocked", reason="pdt_throttle")

    stop_price = position_sizer.stop_loss_price(current_price, stop_pct)
    target_price = position_sizer.take_profit_price(current_price, take_profit_pct)
    shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
    if shares <= 0:
        return TradeDecision(action="hold", reason="position size rounds to zero shares")

    return TradeDecision(
        action="buy", reason="all checks passed",
        shares=shares, stop_price=stop_price, target_price=target_price,
    )
```

Note: `drawdown_breaker_ok` is passed in as a bool (the caller calls
`drawdown_breaker.update_equity(...)` then `drawdown_breaker.can_open_new_trade()` itself)
rather than `decide_trade` taking the `DrawdownBreaker` object directly — this keeps
`decide_trade` from needing to know the caller's current equity snapshot timing, which
differs between the backtester (bar close) and the live loop (latest account equity poll).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add graywind_strategy/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire signal, gates, and risk checks into a single decide_trade pipeline"
```

---

### Task 11: Hand-Rolled Backtester + PDT-Compliance Assertion

**Files:**
- Create: `graywind_strategy/backtester.py`
- Test: `tests/test_backtester.py`

**Interfaces:**
- Consumes: Task 5's CSVs (loaded via pandas), `compute_signals` (Task 6), `decide_trade`
  (Task 10), `PDTThrottle`/`PositionSizer`/`DrawdownBreaker` (Tasks 2-4).
- Produces: `sharpe_ratio(equity_curve: list[float], periods_per_year: int) -> float`,
  `max_drawdown(equity_curve: list[float]) -> float`, `win_rate(trades: list[dict]) ->
  float` (all pure, unit-tested with fabricated data) and `run_backtest(df_by_symbol:
  dict[str, pd.DataFrame], starting_equity=10000.0, gates_always_pass=False) ->
  BacktestResult` (integration-verified with a real run against real fetched data, not
  unit-tested against mocks — this project's standing discipline: a claim like "the PDT
  throttle works in a real backtest" requires an actual run, not code review standing in
  for one). Task 13 (burn-in decision) reads this task's real output.

- [ ] **Step 1: Write the failing tests for the pure stats functions**

Create `tests/test_backtester.py`:

```python
from graywind_strategy.backtester import max_drawdown, sharpe_ratio, win_rate


def test_sharpe_ratio_of_flat_equity_curve_is_zero():
    # Zero variance in returns -> Sharpe is defined as 0.0, not a division error.
    assert sharpe_ratio([10000, 10000, 10000, 10000], periods_per_year=252) == 0.0


def test_sharpe_ratio_positive_for_a_steadily_rising_equity_curve():
    curve = [10000 * (1.001 ** i) for i in range(50)]
    assert sharpe_ratio(curve, periods_per_year=252) > 0.0


def test_max_drawdown_of_monotonically_rising_curve_is_zero():
    assert max_drawdown([100, 110, 120, 130]) == 0.0


def test_max_drawdown_measures_the_worst_peak_to_trough_drop():
    # Peak 150, trough 120 -> (150-120)/150 = 0.2
    assert max_drawdown([100, 150, 130, 120, 140]) == 0.2


def test_win_rate_of_no_trades_is_zero():
    assert win_rate([]) == 0.0


def test_win_rate_counts_profitable_round_trips():
    trades = [
        {"symbol": "AAPL", "action": "buy", "price": 100.0, "shares": 10},
        {"symbol": "AAPL", "action": "sell", "price": 105.0, "shares": 10},  # +$50, win
        {"symbol": "SPY", "action": "buy", "price": 400.0, "shares": 5},
        {"symbol": "SPY", "action": "sell", "price": 395.0, "shares": 5},   # -$25, loss
    ]
    assert win_rate(trades) == 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtester.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.backtester'`

- [ ] **Step 3: Write the stats functions and the bar-by-bar backtest loop**

Create `graywind_strategy/backtester.py`:

```python
"""Hand-rolled bar-by-bar backtester: replays decide_trade() over historical
data for each symbol independently, then computes Sharpe ratio, max
drawdown, and win rate from the resulting equity curve and trade log.
Also verifies no rolling 5-business-day window in the backtest period ever
exceeded 3 day-trades — the PDT throttle checked against real historical
simulation, not just trusted from code review.
"""
import statistics
from dataclasses import dataclass, field

from graywind_strategy.pipeline import decide_trade
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.strategy_engine import compute_signals


@dataclass
class BacktestResult:
    equity_curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    pdt_compliant: bool = True


def sharpe_ratio(equity_curve, periods_per_year=252):
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]
    if len(returns) < 2 or statistics.pstdev(returns) == 0:
        return 0.0
    return (statistics.mean(returns) / statistics.pstdev(returns)) * (periods_per_year ** 0.5)


def max_drawdown(equity_curve):
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    return worst


def win_rate(trades):
    round_trips = []
    open_by_symbol = {}
    for trade in trades:
        symbol = trade["symbol"]
        if trade["action"] == "buy":
            open_by_symbol[symbol] = trade
        elif trade["action"] == "sell":
            opened = open_by_symbol.pop(symbol, None)
            if opened is not None:
                pnl = (trade["price"] - opened["price"]) * trade["shares"]
                round_trips.append(pnl > 0)
    if not round_trips:
        return 0.0
    return sum(round_trips) / len(round_trips)


def run_backtest(df_by_symbol, starting_equity=10000.0,
                  fred_api_key=None, news_client=None, finnhub_api_key=None):
    """Runs decide_trade() bar-by-bar for every symbol, in timestamp order
    across symbols so PDT/drawdown state is shared correctly. Assumes each
    DataFrame in df_by_symbol already has a 'time' column (from Task 5's
    CSV format) and a 'close' column."""
    signals_by_symbol = {
        symbol: compute_signals(df) for symbol, df in df_by_symbol.items()
    }
    pdt_throttle = PDTThrottle()
    position_sizer = PositionSizer(risk_fraction=0.01)
    drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)

    all_rows = []
    for symbol, df in signals_by_symbol.items():
        for _, row in df.iterrows():
            all_rows.append((row["time"], symbol, row))
    all_rows.sort(key=lambda r: r[0])

    equity = starting_equity
    equity_curve = []
    trades = []
    open_positions = {}
    current_day = None

    for time, symbol, row in all_rows:
        as_of_date = time.date() if hasattr(time, "date") else time
        if as_of_date != current_day:
            current_day = as_of_date
            drawdown_breaker.start_new_day(current_day, equity)

        price = row["close"]

        position = open_positions.get(symbol)
        if position is not None and (price <= position["stop"] or price >= position["target"]):
            equity += (price - position["entry_price"]) * position["shares"]
            trades.append({"symbol": symbol, "action": "sell", "price": price, "shares": position["shares"]})
            if position["opened_date"] == current_day:
                pdt_throttle.record_day_trade(current_day)
            del open_positions[symbol]

        drawdown_breaker.update_equity(equity)

        if symbol not in open_positions:
            decision = decide_trade(
                symbol=symbol, signal=row["signal"], as_of_date=current_day,
                current_price=price, account_equity=equity,
                pdt_throttle=pdt_throttle, position_sizer=position_sizer,
                drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
                fred_api_key=fred_api_key, news_client=news_client,
                finnhub_api_key=finnhub_api_key,
            )
            if decision.action == "buy":
                open_positions[symbol] = {
                    "entry_price": price, "shares": decision.shares,
                    "stop": decision.stop_price, "target": decision.target_price,
                    "opened_date": current_day,
                }
                trades.append({"symbol": symbol, "action": "buy", "price": price, "shares": decision.shares})

        equity_curve.append(equity)

    pdt_compliant = _check_pdt_compliance(trades_with_dates=[
        (t["symbol"], t["action"], time) for time, symbol, _ in all_rows for t in trades
        if t["symbol"] == symbol
    ]) if trades else True

    return BacktestResult(
        equity_curve=equity_curve, trades=trades,
        sharpe=sharpe_ratio(equity_curve) if equity_curve else 0.0,
        max_drawdown=max_drawdown(equity_curve) if equity_curve else 0.0,
        win_rate=win_rate(trades),
        pdt_compliant=pdt_compliant,
    )


def _check_pdt_compliance(trades_with_dates):
    day_trade_dates = []
    open_date_by_symbol = {}
    for symbol, action, time in sorted(trades_with_dates, key=lambda t: t[2]):
        trade_date = time.date() if hasattr(time, "date") else time
        if action == "buy":
            open_date_by_symbol[symbol] = trade_date
        elif action == "sell":
            opened = open_date_by_symbol.pop(symbol, None)
            if opened == trade_date:
                day_trade_dates.append(trade_date)

    throttle = PDTThrottle()
    for trade_date in sorted(day_trade_dates):
        if not throttle.can_open_day_trade(trade_date):
            return False
        throttle.record_day_trade(trade_date)
    return True
```

Note on `_check_pdt_compliance`'s trade-pairing: this re-derives day-trades from the
`trades` log the same way Task 5-era LEAN plan's `verify_pdt_compliance.py` did — pairing
a buy with the next sell of the same symbol. Whoever implements this task should
double-check the pairing logic against `run_backtest`'s own trade log shape once real
output exists (Step 4 below), since this is exactly the kind of "trust the real run over
the plan's prose" check this project's discipline calls for.

- [ ] **Step 4: Run the pure-function tests to verify they pass**

Run: `python -m pytest tests/test_backtester.py -v`
Expected: 6 passed

- [ ] **Step 5: Run a real integration backtest against real fetched data**

Requires Task 5's `fetch_alpaca_data.py` to have been run already with real Alpaca
credentials, and requires real `FRED_API_KEY` / `FINNHUB_API_KEY` values (see Task 12 for
how to obtain them — if not yet obtained, pass `fred_api_key=None` and stub
`evaluate_vix_gate`/`evaluate_earnings_gate` to always return `True` for this one
integration run, noting in the commit message that gates were bypassed for this
particular verification run pending real keys).

Run a short script (interactively or as a throwaway file, not committed) equivalent to:
```python
import pandas as pd
from graywind_strategy.backtester import run_backtest

df_by_symbol = {
    "AAPL": pd.read_csv("alpaca_data/aapl.csv", parse_dates=["time"]),
    "SPY": pd.read_csv("alpaca_data/spy.csv", parse_dates=["time"]),
}
result = run_backtest(df_by_symbol, starting_equity=10000.0)
print(f"trades={len(result.trades)} sharpe={result.sharpe:.3f} "
      f"max_drawdown={result.max_drawdown:.3f} win_rate={result.win_rate:.3f} "
      f"pdt_compliant={result.pdt_compliant}")
```
Expected: runs without exception, prints real numbers, and `pdt_compliant` is `True` (if
`False`, there is a real bug in Task 10's PDT wiring — `decide_trade` should never approve
a buy that `pdt_throttle.can_open_day_trade` would reject — fix before proceeding). If
`trades` is 0, the RSI/MA thresholds may be too strict for the fetched data window — note
this as a real strategy-tuning finding for Task 13, not a plan defect.

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/backtester.py tests/test_backtester.py
git commit -m "feat: add hand-rolled bar-by-bar backtester with PDT-compliance verification"
```

---

### Task 12: Live Scheduled-Loop Trading Script

**Files:**
- Create: `graywind_strategy/state_store.py`
- Create: `live_loop.py`
- Test: `tests/test_state_store.py`
- Test: `tests/test_live_loop.py`
- Create: `.env.example`

**Interfaces:**
- Consumes: Task 10's `decide_trade`, Tasks 2-4's risk classes, real `ALPACA_API_KEY`/
  `ALPACA_API_SECRET`/`FRED_API_KEY`/`FINNHUB_API_KEY` environment variables.
- Produces: a single-shot script meant to be invoked every 15 minutes by an external
  scheduler (cron/launchd) during market hours only — mirroring the Bullion project's
  cron-driven data pipeline rather than running a persistent process. Because each
  invocation is a fresh process, `PDTThrottle`/`DrawdownBreaker` state must be
  reconstructed from a small local JSON file at the start of each run and saved back at
  the end — `state_store.py` handles that persistence.

- [ ] **Step 1: Write the failing tests for state persistence**

Create `tests/test_state_store.py`:

```python
from datetime import date

from graywind_strategy.state_store import load_state, save_state


def test_load_state_returns_empty_defaults_when_no_file_exists(tmp_path):
    state = load_state(path=str(tmp_path / "nonexistent.json"))
    assert state == {"day_trade_dates": [], "day": None, "starting_equity": None}


def test_save_then_load_round_trips_state(tmp_path):
    path = str(tmp_path / "state.json")
    save_state(
        {"day_trade_dates": ["2024-01-08", "2024-01-09"], "day": "2024-01-09", "starting_equity": 10000.0},
        path=path,
    )
    state = load_state(path=path)
    assert state["day_trade_dates"] == ["2024-01-08", "2024-01-09"]
    assert state["day"] == "2024-01-09"
    assert state["starting_equity"] == 10000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_state_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'graywind_strategy.state_store'`

- [ ] **Step 3: Write `state_store.py`**

Create `graywind_strategy/state_store.py`:

```python
"""Persists PDT-throttle and drawdown-breaker state to a local JSON file
between live_loop.py invocations, since each run is a fresh process (a
cron-invoked script, not a long-running one)."""
import json
import os

DEFAULT_STATE_PATH = "state/live_state.json"


def load_state(path=DEFAULT_STATE_PATH):
    if not os.path.exists(path):
        return {"day_trade_dates": [], "day": None, "starting_equity": None}
    with open(path) as f:
        return json.load(f)


def save_state(state, path=DEFAULT_STATE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state_store.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing tests for the market-hours check**

Create `tests/test_live_loop.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from live_loop import is_market_hours

ET = ZoneInfo("America/New_York")


def test_is_market_hours_true_during_regular_session():
    assert is_market_hours(now=datetime(2024, 1, 8, 10, 0, tzinfo=ET)) is True  # Mon 10am


def test_is_market_hours_false_before_open():
    assert is_market_hours(now=datetime(2024, 1, 8, 9, 0, tzinfo=ET)) is False  # Mon 9am


def test_is_market_hours_false_after_close():
    assert is_market_hours(now=datetime(2024, 1, 8, 16, 30, tzinfo=ET)) is False  # Mon 4:30pm


def test_is_market_hours_false_on_weekend():
    assert is_market_hours(now=datetime(2024, 1, 6, 10, 0, tzinfo=ET)) is False  # Saturday
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `python -m pytest tests/test_live_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'live_loop'`

- [ ] **Step 7: Write `live_loop.py`**

Create `live_loop.py`:

```python
#!/usr/bin/env python3
"""Single-shot live trading script: fetches the latest bar and gate data
for each symbol in the Phase 1 watchlist, runs decide_trade(), and places
any resulting order against Alpaca's paper endpoint. Meant to be invoked
every 15 minutes by an external scheduler (cron/launchd) during market
hours only — this script checks market hours itself and exits early
outside them, so it is safe to schedule unconditionally every 15 minutes
around the clock.

Requires: ALPACA_API_KEY, ALPACA_API_SECRET, FRED_API_KEY, FINNHUB_API_KEY
in the environment. See .env.example.
"""
import os
import sys
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from fetch_alpaca_data import fetch_bars
from graywind_strategy.pipeline import decide_trade
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.state_store import load_state, save_state
from graywind_strategy.strategy_engine import compute_signals

WATCHLIST = ["AAPL", "SPY"]
MARKET_OPEN = dt_time(9, 30)
MARKET_CLOSE = dt_time(16, 0)
ET = ZoneInfo("America/New_York")
# 3 calendar days of 15-min bars comfortably covers the 30-period slow SMA's
# warm-up (30 bars ~ 1.25 trading days at 15-min resolution on a 6.5h session).
SIGNAL_LOOKBACK = timedelta(days=3)


def is_market_hours(now=None):
    now = now or datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _restore_pdt_throttle(state):
    throttle = PDTThrottle()
    for iso_date in state["day_trade_dates"]:
        throttle.record_day_trade(datetime.fromisoformat(iso_date).date())
    return throttle


def main():
    if not is_market_hours():
        print("outside market hours, exiting")
        return 0

    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    fred_api_key = os.environ.get("FRED_API_KEY")
    finnhub_api_key = os.environ.get("FINNHUB_API_KEY")
    if not all([api_key, api_secret, fred_api_key, finnhub_api_key]):
        print("ERROR: one or more required API keys are not set in the environment", file=sys.stderr)
        return 1

    trading_client = TradingClient(api_key, api_secret, paper=True)
    data_client = StockHistoricalDataClient(api_key, api_secret)
    news_client = NewsClient(api_key, api_secret)

    account = trading_client.get_account()
    equity = float(account.equity)
    today = datetime.now(ET).date()

    state = load_state()
    pdt_throttle = _restore_pdt_throttle(state)
    drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    starting_equity = state["starting_equity"] if state["day"] == today.isoformat() else equity
    drawdown_breaker.start_new_day(today, starting_equity)
    drawdown_breaker.update_equity(equity)

    position_sizer = PositionSizer(risk_fraction=0.01)

    now = datetime.now(ET)
    for symbol in WATCHLIST:
        bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
        if not bars:
            print(f"{symbol}: no recent bars returned, skipping this cycle")
            continue
        df = pd.DataFrame([
            {"time": bar.timestamp, "close": bar.close} for bar in bars
        ])
        df = compute_signals(df)
        latest = df.iloc[-1]
        signal = latest["signal"]
        current_price = latest["close"]

        decision = decide_trade(
            symbol=symbol, signal=signal, as_of_date=today,
            current_price=current_price, account_equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=position_sizer,
            drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
            fred_api_key=fred_api_key, news_client=news_client,
            finnhub_api_key=finnhub_api_key,
        )

        if decision.action == "buy":
            order = MarketOrderRequest(
                symbol=symbol, qty=decision.shares,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            trading_client.submit_order(order)
            pdt_throttle.record_day_trade(today)
            print(f"{symbol}: submitted buy for {decision.shares} shares")
        else:
            print(f"{symbol}: {decision.action} ({decision.reason})")

    save_state({
        "day_trade_dates": [d.isoformat() for d in pdt_throttle._day_trade_dates],
        "day": today.isoformat(),
        "starting_equity": starting_equity,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note: `fetch_bars` is imported directly from `fetch_alpaca_data` (Task 5) rather than
reimplemented — same Alpaca bars-request pattern, just a 3-day lookback instead of 180
days, and fed into `compute_signals` (Task 6) exactly as the backtester does, so live and
backtest signal computation cannot silently drift apart.

- [ ] **Step 8: Run the market-hours tests to verify they pass**

Run: `python -m pytest tests/test_live_loop.py tests/test_state_store.py -v`
Expected: 6 passed (the `main()` function itself is not unit-tested here — it requires
real network calls and is verified in Step 9 below, matching this project's standing
"integration validation via a real run" discipline).

- [ ] **Step 9: Document required environment variables without committing them**

Create `.env.example`:

```
ALPACA_API_KEY=your_paper_key_here
ALPACA_API_SECRET=your_paper_secret_here
FRED_API_KEY=your_fred_key_here
FINNHUB_API_KEY=your_finnhub_key_here
```

Set the real values as actual environment variables locally — never write real key values
into `.env.example` or any committed file. Sign up for FRED (fredaccount.stlouisfed.org,
instant free key) and Finnhub (finnhub.io/register, instant free key, no card) if not
already done.

- [ ] **Step 10: Verify a dry run outside market hours**

Run: `python live_loop.py`
Expected (if run outside 9:30am-4:00pm ET Mon-Fri): prints `outside market hours,
exiting` and exits 0 — confirms the script imports cleanly and the market-hours gate
works, without needing real credentials yet. A full live-during-market-hours run (real
bar fetch, real order submission) can only be verified during real trading hours, with
real credentials in place.

- [ ] **Step 11: Commit**

```bash
git add graywind_strategy/state_store.py live_loop.py tests/test_state_store.py tests/test_live_loop.py .env.example
git commit -m "feat: add cron-driven live trading script with persisted PDT/drawdown state"
```

---

### Task 13: Burn-In Length Decision

**Files:**
- Create: `docs/superpowers/burn-in-decision.md`

**Interfaces:**
- Consumes: Task 11's real backtest statistics (Sharpe ratio, max drawdown, win rate,
  trade count) and PDT-compliance result.
- Produces: a written, dated decision on how long Graywind paper-trades live before
  Phase 2 (ML) or Phase 3 (real capital) work begins — the spec requires this be an
  explicit decision, not silently skipped.

- [ ] **Step 1: Pull the real backtest numbers from Task 11's Step 5 run**

Re-run the integration script from Task 11 Step 5 if the numbers were not saved, and
record the actual `sharpe`, `max_drawdown`, `win_rate`, `len(result.trades)`, and
`pdt_compliant` values it prints.

- [ ] **Step 2: Write the decision doc**

Create `docs/superpowers/burn-in-decision.md`, filling in the real numbers from Step 1
(the template below shows the required structure — replace every bracketed value with
the actual backtest output, do not leave any bracket unfilled):

```markdown
# Graywind Phase 1 — Paper-Trading Burn-In Decision

**Date:** [today's date]

**Backtest results this decision is based on** (from `run_backtest`, Task 11 Step 5):
- Sharpe Ratio: [value]
- Max Drawdown: [value]
- Win Rate: [value]
- Total trades: [value]
- PDT compliance: [True / False]

**Decision:** paper-trade live for [N weeks/months] before considering Phase 2 (ML model)
or Phase 3 (real capital).

**Rationale:** [1-3 sentences connecting the actual numbers above to the chosen length —
e.g. a weak or negative Sharpe ratio argues for a longer burn-in or a return to strategy
tuning before burn-in even starts; a strong Sharpe still needs enough calendar time to
cross varied day-to-day conditions, not just a lucky short window.]
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/burn-in-decision.md
git commit -m "docs: record Phase 1 paper-trading burn-in decision"
```
