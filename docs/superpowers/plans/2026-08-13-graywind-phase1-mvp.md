# Graywind Phase 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working, backtestable, PDT-compliant rule-based intraday equities trading
pipeline (data → RSI/MA-crossover signal → risk-checked order → paper fill →
backtest/live evaluation) on LEAN Engine + Alpaca, proving the pipeline end-to-end before
any ML or real capital.

**Architecture:** A LEAN CLI project (`graywind_strategy/`) holds the `QCAlgorithm` and
three pure-Python risk-management modules with zero LEAN dependency (independently unit
testable). A root-level `fetch_alpaca_data.py` script pulls historical bars from Alpaca
into local CSVs, which a custom `PythonData` reader feeds into `lean backtest`. The same
algorithm code runs unchanged in live paper mode via LEAN's native Alpaca live-data
integration.

**Tech Stack:** Python 3.11+, `lean` (LEAN CLI, Docker-backed), `alpaca-py`, `pytest`.

## Global Constraints

- Asset class: US equities only — fixed two-symbol watchlist (AAPL, SPY). No other
  symbols in Phase 1.
- Framework: LEAN Engine via `lean-cli` + Docker, run fully locally. No QuantConnect
  Cloud subscription.
- Timeframe: 15-minute bars only (not 5-minute, not daily).
- Capital assumption: under $25k → PDT rule is a hard constraint: max 3 day-trades
  (opened + closed same session) per rolling 5 business days.
- Broker/data: Alpaca — free paper trading + free historical/live bars via the IEX feed.
  $0 cost. Never use QuantConnect's own paid historical datasets.
- Risk: fixed-fractional position sizing at 1% of account equity risked per trade; daily
  drawdown circuit breaker at 2% of starting-of-day equity.
- Orders: market orders only. No limit orders, no partial-fill handling.
- Position sizing: fixed-fractional only. No Kelly Criterion.
- Trading hours: US equities regular session only (~9:30am–4:00pm ET, Mon–Fri, no
  holidays). No extended hours, no 24/7 operation.
- Strategy: rule-based only (RSI + moving-average crossover). No ML/RL model.
- No real capital anywhere in this plan — paper trading only.
- Never commit real Alpaca API keys/secrets. Read from environment variables only;
  `.gitignore` covers any local secret files.

---

### Task 1: Environment Setup + Repo/LEAN Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create (via `lean init`): `lean.json`, `data/` (LEAN's own reference data cache)
- Create (via `lean project-create`): `graywind_strategy/main.py`,
  `graywind_strategy/config.json`, `graywind_strategy/research.ipynb`
- Create: `graywind_strategy/__init__.py`
- Create: `graywind_strategy/risk/__init__.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the repo skeleton every later task builds inside — specifically the
  `graywind_strategy/` package (with `risk/` subpackage) and repo-root Python environment
  that `tests/` (Task 2+) and `fetch_alpaca_data.py` (Task 5) run inside.

- [ ] **Step 1: Write `requirements.txt`**

```
lean
alpaca-py
pytest
```

- [ ] **Step 2: Write `.gitignore`**

```
data/
alpaca_data/
__pycache__/
*.pyc
.venv/
venv/
.env
backtests/
```

- [ ] **Step 3: Verify Python and Docker are available**

Run: `python3 --version && docker --version`
Expected: Python 3.11 or higher, and a Docker version string (Docker Desktop must already
be running). If either is missing: install Python 3.11+ from python.org and Docker
Desktop from docker.com — this is a one-time manual install, not something this plan can
script. Do not proceed until both commands succeed.

- [ ] **Step 4: Create a virtual environment and install dependencies**

Run:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
Expected: `lean`, `alpaca-py`, and `pytest` install without error.

- [ ] **Step 5: Initialize the LEAN CLI workspace**

Run: `lean init`
Expected: creates `lean.json` and a `data/` folder (LEAN's own bundled free sample
market data — this is separate from and not to be confused with the Alpaca data Task 5
fetches; `data/` is gitignored per Step 2).

- [ ] **Step 6: Create the LEAN algorithm project**

Run: `lean project-create "graywind_strategy" --language python`
Expected: creates `graywind_strategy/main.py`, `graywind_strategy/config.json`,
`graywind_strategy/research.ipynb`.

- [ ] **Step 7: Turn `graywind_strategy` into an importable Python package for pytest**

Create `graywind_strategy/__init__.py` (empty file) and `graywind_strategy/risk/__init__.py`
(empty file, first create the `graywind_strategy/risk/` directory).

- [ ] **Step 8: Verify the scaffold**

Run: `ls graywind_strategy/main.py graywind_strategy/__init__.py graywind_strategy/risk/__init__.py lean.json`
Expected: all four paths listed, no "No such file" errors.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .gitignore lean.json graywind_strategy/__init__.py graywind_strategy/risk/__init__.py graywind_strategy/main.py graywind_strategy/config.json graywind_strategy/research.ipynb
git commit -m "chore: scaffold repo, LEAN CLI workspace, and graywind_strategy project"
```

---

### Task 2: PDT Day-Trade Throttle

**Files:**
- Create: `graywind_strategy/risk/pdt_throttle.py`
- Test: `tests/test_pdt_throttle.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PDTThrottle` class with `record_day_trade(trade_date: date) -> None` and
  `can_open_day_trade(as_of: date) -> bool`. Task 7 imports this as
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
  `take_profit_price(entry_price: float, take_profit_pct: float) -> float`. Task 7 imports
  this as `from graywind_strategy.risk.position_sizing import PositionSizer`.

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
  `update_equity(current_equity: float) -> None`, `can_open_new_trade() -> bool`. Task 7
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
  `time` formatted `%Y-%m-%d %H:%M:%S`. Task 8's custom `PythonData` reader consumes this
  exact format/path convention.

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
(AAPL, SPY) from Alpaca and writes them to local CSVs for LEAN's backtest
data path. Requires ALPACA_API_KEY / ALPACA_API_SECRET in the environment.
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

### Task 6: Strategy Engine — RSI + MA Crossover Algorithm (smoke-tested on LEAN's bundled sample data)

**Files:**
- Modify: `graywind_strategy/main.py`

**Interfaces:**
- Consumes: LEAN's `AlgorithmImports` (framework-provided), LEAN's own bundled free
  sample data (from `lean init`, Task 1) for this task's smoke test only — NOT Alpaca
  data, which arrives in Task 8.
- Produces: `GraywindPhase1Algorithm(QCAlgorithm)` class with an `evaluate_signal()`
  method returning `"buy"`, `"sell"`, or `"hold"`, called from `OnData`. Task 7 wires risk
  checks around this method's output before any order is placed.

This task's verification is a real `lean backtest` run (LEAN algorithms can't be
meaningfully unit-tested with pytest — they depend on the QuantConnect SDK objects LEAN's
Docker container provides). Using LEAN's own bundled sample data here (rather than
Alpaca's) is deliberate: it's free, already present from `lean init`, and lets us confirm
the algorithm code itself runs correctly before Task 8 wires in the real Alpaca-sourced
data path — it is not a violation of the "no QuantConnect paid data" constraint, since
this bundled sample is free and used only as a smoke test, not as Phase 1's real dataset.

- [ ] **Step 1: Replace the scaffolded `graywind_strategy/main.py` with the strategy skeleton**

Seeded from `QuantConnect/Lean`'s own `Algorithm.Python/MovingAverageCrossAlgorithm.py`
example plus its RSI indicator example (see spec's "Open-source references" section),
adapted for a 15-minute-consolidated RSI+MA crossover on AAPL/SPY:

```python
# graywind_strategy/main.py
from AlgorithmImports import *


class GraywindPhase1Algorithm(QCAlgorithm):
    RSI_PERIOD = 14
    FAST_SMA_PERIOD = 10
    SLOW_SMA_PERIOD = 30
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70
    BAR_SIZE_MINUTES = 15

    def Initialize(self):
        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 6, 1)
        self.SetCash(10000)

        self.symbols = {}
        for ticker in ["AAPL", "SPY"]:
            symbol = self.AddEquity(ticker, Resolution.Minute).Symbol
            consolidator = TradeBarConsolidator(timedelta(minutes=self.BAR_SIZE_MINUTES))
            self.SubscriptionManager.AddConsolidator(symbol, consolidator)

            rsi = RelativeStrengthIndex(self.RSI_PERIOD)
            fast = SimpleMovingAverage(self.FAST_SMA_PERIOD)
            slow = SimpleMovingAverage(self.SLOW_SMA_PERIOD)
            self.RegisterIndicator(symbol, rsi, consolidator)
            self.RegisterIndicator(symbol, fast, consolidator)
            self.RegisterIndicator(symbol, slow, consolidator)

            self.symbols[symbol] = {"rsi": rsi, "fast": fast, "slow": slow}

    def OnData(self, data):
        for symbol, indicators in self.symbols.items():
            rsi, fast, slow = indicators["rsi"], indicators["fast"], indicators["slow"]
            if not (rsi.IsReady and fast.IsReady and slow.IsReady):
                continue
            signal = self.evaluate_signal(rsi.Current.Value, fast.Current.Value, slow.Current.Value)
            self.act_on_signal(symbol, signal)

    def evaluate_signal(self, rsi_value, fast_value, slow_value):
        if fast_value > slow_value and rsi_value < self.RSI_OVERBOUGHT:
            return "buy"
        if fast_value < slow_value and rsi_value > self.RSI_OVERSOLD:
            return "sell"
        return "hold"

    def act_on_signal(self, symbol, signal):
        # Task 7 replaces this body with PDT/position-sizing/drawdown-checked orders.
        if signal == "buy" and not self.Portfolio[symbol].Invested:
            self.SetHoldings(symbol, 0.5)
        elif signal == "sell" and self.Portfolio[symbol].Invested:
            self.Liquidate(symbol)
```

- [ ] **Step 2: Run a smoke-test backtest**

Run: `lean backtest graywind_strategy`
Expected: the backtest completes without a Python exception in the log output, and the
final statistics report is printed (Sharpe Ratio, Drawdown, etc. — values themselves
don't matter yet, only that it ran end-to-end against LEAN's bundled sample data).

- [ ] **Step 3: Commit**

```bash
git add graywind_strategy/main.py
git commit -m "feat: add RSI+MA-crossover strategy engine, smoke-tested on LEAN sample data"
```

---

### Task 7: Wire Risk Management Into the Strategy Engine

**Files:**
- Modify: `graywind_strategy/main.py`

**Interfaces:**
- Consumes: `PDTThrottle` (Task 2), `PositionSizer` (Task 3), `DrawdownBreaker` (Task 4)
  — imported inside the LEAN project as `from risk.pdt_throttle import PDTThrottle`,
  `from risk.position_sizing import PositionSizer`, `from risk.drawdown_breaker import DrawdownBreaker`
  (relative to the `graywind_strategy/` folder, since LEAN's Docker container mounts that
  folder as its own root — different import path than the `graywind_strategy.risk.*` used
  by `tests/`, same underlying files).
- Produces: `act_on_signal` now routes every entry through all three risk checks, and a
  new `check_stop_and_target` method gives every open position an actual price-triggered
  exit — not just a sell signal from the RSI/MA crossover. This closes a gap the spec
  calls out explicitly ("Per-trade stop-loss / take-profit" is a named risk behavior, not
  just an input to position sizing): without this, a position could ride a loss well past
  its stop or a win well past its target while waiting for the crossover to reverse.

- [ ] **Step 1: Import the risk modules and instantiate them in `Initialize`**

Modify `graywind_strategy/main.py` — add near the top, after `from AlgorithmImports import *`:

```python
from risk.pdt_throttle import PDTThrottle
from risk.position_sizing import PositionSizer
from risk.drawdown_breaker import DrawdownBreaker
```

Add to the end of `Initialize`:

```python
        self.pdt_throttle = PDTThrottle()
        self.position_sizer = PositionSizer(risk_fraction=0.01)
        self.drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.AfterMarketOpen("SPY", 0),
            self.on_market_open,
        )
        self._open_positions = {}  # symbol -> {"opened_date", "stop", "target"}
```

- [ ] **Step 2: Add the market-open handler that starts each trading day**

Add a new method to the class. Note this only resets the drawdown breaker's daily
baseline — `_open_positions` is NOT cleared here, since a position can legitimately span
multiple days (holding overnight is not a day-trade under PDT rules and isn't restricted
by this project's scope):

```python
    def on_market_open(self):
        self.drawdown_breaker.start_new_day(self.Time.date(), self.Portfolio.TotalPortfolioValue)
```

- [ ] **Step 3: Add the stop-loss/take-profit exit check**

Add a new method to the class:

```python
    def check_stop_and_target(self, symbol):
        position = self._open_positions.get(symbol)
        if position is None:
            return False
        price = self.Securities[symbol].Price
        if price <= position["stop"] or price >= position["target"]:
            self.Liquidate(symbol)
            if position["opened_date"] == self.Time.date():
                self.pdt_throttle.record_day_trade(self.Time.date())
            del self._open_positions[symbol]
            self.Debug(f"{self.Time} {symbol}: stop/target exit at {price}")
            return True
        return False
```

- [ ] **Step 4: Call the stop/target check first in `OnData`, before evaluating the signal**

Replace the `OnData` method (written in Task 6) with:

```python
    def OnData(self, data):
        for symbol, indicators in self.symbols.items():
            if self.check_stop_and_target(symbol):
                continue
            rsi, fast, slow = indicators["rsi"], indicators["fast"], indicators["slow"]
            if not (rsi.IsReady and fast.IsReady and slow.IsReady):
                continue
            signal = self.evaluate_signal(rsi.Current.Value, fast.Current.Value, slow.Current.Value)
            self.act_on_signal(symbol, signal)
```

- [ ] **Step 5: Replace `act_on_signal` with the risk-checked version**

Replace the entire `act_on_signal` method:

```python
    def act_on_signal(self, symbol, signal):
        self.drawdown_breaker.update_equity(self.Portfolio.TotalPortfolioValue)
        if not self.drawdown_breaker.can_open_new_trade():
            self.Debug(f"{self.Time} {symbol}: blocked by drawdown breaker")
            return

        if signal == "buy" and not self.Portfolio[symbol].Invested:
            if not self.pdt_throttle.can_open_day_trade(self.Time.date()):
                self.Debug(f"{self.Time} {symbol}: blocked by PDT throttle")
                return
            price = self.Securities[symbol].Price
            stop_price = self.position_sizer.stop_loss_price(price, stop_pct=0.02)
            target_price = self.position_sizer.take_profit_price(price, take_profit_pct=0.03)
            shares = self.position_sizer.shares_to_buy(
                self.Portfolio.TotalPortfolioValue, price, stop_price
            )
            if shares > 0:
                self.MarketOrder(symbol, shares)
                self._open_positions[symbol] = {
                    "opened_date": self.Time.date(),
                    "stop": stop_price,
                    "target": target_price,
                }
                self.Debug(f"{self.Time} {symbol}: bought {shares} shares, stop={stop_price}, target={target_price}")

        elif signal == "sell" and self.Portfolio[symbol].Invested:
            self.Liquidate(symbol)
            position = self._open_positions.pop(symbol, None)
            if position and position["opened_date"] == self.Time.date():
                self.pdt_throttle.record_day_trade(self.Time.date())
            self.Debug(f"{self.Time} {symbol}: liquidated on reversal signal")
```

- [ ] **Step 6: Run a backtest to verify it still runs end-to-end**

Run: `lean backtest graywind_strategy`
Expected: completes without a Python exception; the log output (printed to the console
and saved under `graywind_strategy/backtests/<timestamp>/log.txt`) shows at least one
`Debug` line from the code above — an order being placed, a stop/target exit, a
reversal-signal liquidation, or a block by the drawdown breaker or PDT throttle.

- [ ] **Step 7: Commit**

```bash
git add graywind_strategy/main.py
git commit -m "feat: route entries through risk checks and give every position a real stop/target exit"
```

---

### Task 8: Custom Alpaca CSV Data Source + Real Backtest with PDT-Compliance Assertion

**Files:**
- Create: `graywind_strategy/custom_data.py`
- Modify: `graywind_strategy/main.py`
- Create: `graywind_strategy/verify_pdt_compliance.py`

**Interfaces:**
- Consumes: Task 5's CSV format/path (`alpaca_data/<symbol_lowercased>.csv`,
  `time,open,high,low,close,volume`). Requires the user to have run
  `ALPACA_API_KEY=... ALPACA_API_SECRET=... python fetch_alpaca_data.py` first with real
  paper-account credentials (Task 9 covers obtaining these).
- Produces: `AlpacaCsvBar(PythonData)` class; `graywind_strategy/main.py` now reads AAPL/
  SPY from `alpaca_data/*.csv` instead of LEAN's bundled sample data; a real backtest run
  against that data, with a PDT-compliance check script other tasks/future sessions can
  re-run against any backtest's orders output.

- [ ] **Step 1: Write the custom `PythonData` CSV reader**

Create `graywind_strategy/custom_data.py`:

```python
from AlgorithmImports import *
from datetime import datetime


class AlpacaCsvBar(PythonData):
    def GetSource(self, config, date, isLiveMode):
        source = f"alpaca_data/{config.Symbol.Value.lower()}.csv"
        return SubscriptionDataSource(source, SubscriptionTransportMedium.LocalFile)

    def Reader(self, config, line, date, isLiveMode):
        if not line or line.startswith("time"):
            return None
        parts = line.split(",")
        bar = AlpacaCsvBar()
        bar.Symbol = config.Symbol
        bar.Time = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
        bar.Value = float(parts[4])  # close
        bar["Open"] = float(parts[1])
        bar["High"] = float(parts[2])
        bar["Low"] = float(parts[3])
        bar["Close"] = float(parts[4])
        bar["Volume"] = float(parts[5])
        return bar
```

- [ ] **Step 2: Point `Initialize` at the Alpaca CSV data instead of LEAN's bundled data**

In `graywind_strategy/main.py`, add the import:

```python
from custom_data import AlpacaCsvBar
```

Replace the `for ticker in ["AAPL", "SPY"]:` loop's first line
(`symbol = self.AddEquity(ticker, Resolution.Minute).Symbol`) with:

```python
            symbol = self.AddData(AlpacaCsvBar, ticker, Resolution.Minute).Symbol
```

Also update `self.SetStartDate` / `self.SetEndDate` to match whatever date range
`fetch_alpaca_data.py` actually pulled (the last ~180 days as of when it was run) — set
these two lines to real dates covering that range once the CSVs exist, rather than the
placeholder 2024 dates used for Task 6's smoke test.

- [ ] **Step 3: Fetch real Alpaca data and run the real backtest**

Run:
```bash
ALPACA_API_KEY=<your key> ALPACA_API_SECRET=<your secret> python fetch_alpaca_data.py
lean backtest graywind_strategy
```
Expected: `alpaca_data/aapl.csv` and `alpaca_data/spy.csv` exist with real bars; the
backtest completes and produces a results JSON under `graywind_strategy/backtests/`
(check the printed output path). Confirm the statistics report shows a non-zero number of
orders (if zero orders occurred, the RSI/MA crossover thresholds may be too strict for
this data window — that's a real strategy-tuning finding to note, not a plan defect).

- [ ] **Step 4: Write the PDT-compliance assertion script**

Create `graywind_strategy/verify_pdt_compliance.py`:

```python
#!/usr/bin/env python3
"""Reads a LEAN backtest's orders log and asserts no rolling 5-business-day
window ever contained more than 3 day-trades (opened+closed same session).
Run after `lean backtest graywind_strategy`, pointed at that run's results
JSON path (printed by the backtest command).
"""
import json
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, ".")
from graywind_strategy.risk.pdt_throttle import PDTThrottle


def day_trade_dates_from_orders(orders):
    """orders: list of {symbol, direction, time} dicts, chronological.
    A day-trade is an open followed by a close of the same symbol on the
    same calendar date."""
    open_date_by_symbol = {}
    day_trade_dates = []
    for order in orders:
        trade_date = datetime.fromisoformat(order["time"]).date()
        symbol = order["symbol"]
        if order["direction"] == "buy":
            open_date_by_symbol[symbol] = trade_date
        elif order["direction"] == "sell":
            opened = open_date_by_symbol.pop(symbol, None)
            if opened == trade_date:
                day_trade_dates.append(trade_date)
    return day_trade_dates


def main(results_path):
    with open(results_path) as f:
        results = json.load(f)
    orders = results.get("Orders", [])

    day_trade_dates = day_trade_dates_from_orders(orders)
    throttle = PDTThrottle()
    for trade_date in sorted(day_trade_dates):
        if not throttle.can_open_day_trade(trade_date):
            print(f"PDT VIOLATION: day-trade on {trade_date} exceeds the 3-in-5-business-day limit")
            sys.exit(1)
        throttle.record_day_trade(trade_date)

    print(f"PDT compliance OK: {len(day_trade_dates)} day-trades, no 5-business-day window exceeded 3")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: verify_pdt_compliance.py <path-to-backtest-results.json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
```

Note: the exact key names inside LEAN's results JSON (`Orders`, `symbol`/`direction`/
`time` fields) depend on the LEAN version's actual output schema — inspect the real
results JSON produced in Step 3 first (`cat graywind_strategy/backtests/<timestamp>/*.json | head -100`
or open it in an editor) and adjust `day_trade_dates_from_orders`'s field names to match
before trusting this script's output.

- [ ] **Step 5: Run the compliance check against the real backtest**

Run: `python graywind_strategy/verify_pdt_compliance.py graywind_strategy/backtests/<timestamp>/<results-file>.json`
(substitute the actual path printed in Step 3)
Expected: `PDT compliance OK: ...` — if it instead prints `PDT VIOLATION`, the risk wiring
from Task 7 has a real bug (the backtest should never generate a violation, since
`act_on_signal` checks `pdt_throttle.can_open_day_trade` before every buy) and must be
fixed before proceeding.

- [ ] **Step 6: Commit**

```bash
git add graywind_strategy/main.py graywind_strategy/custom_data.py graywind_strategy/verify_pdt_compliance.py
git commit -m "feat: wire real Alpaca-sourced backtest data and PDT-compliance verification"
```

---

### Task 9: Alpaca Paper Account + Live Deploy Configuration

**Files:**
- Modify: `graywind_strategy/config.json` (LEAN project config — brokerage/data-feed
  settings only, no secrets)
- Create: `.env.example`

**Interfaces:**
- Consumes: Task 8's working, PDT-verified algorithm (`graywind_strategy/main.py`
  unchanged in this task — live mode reuses the exact same `Initialize`/`OnData`/
  `act_on_signal` code, per the spec's live-data-path design).
- Produces: a working `lean live deploy` connection to Alpaca's paper endpoint. No new
  application code — this task is credentials + config only.

- [ ] **Step 1: Create an Alpaca paper-trading account (manual, human step)**

Sign up at Alpaca (alpaca.markets), select paper trading (not live), and generate a paper
API key + secret from the dashboard. This cannot be scripted — it requires the account
holder's own signup.

- [ ] **Step 2: Document required environment variables without committing them**

Create `.env.example`:

```
ALPACA_API_KEY=your_paper_key_here
ALPACA_API_SECRET=your_paper_secret_here
```

Set the real values as actual environment variables locally (e.g. in your shell profile
or a local, gitignored `.env` file loaded before running any command) — never write real
key values into `.env.example`, `config.json`, or any committed file.

- [ ] **Step 3: Deploy live via the LEAN CLI**

Run: `lean live deploy graywind_strategy`
Follow the interactive prompts: choose "Alpaca" as the brokerage, confirm paper trading
(not live/real money), and supply the API key/secret when asked (LEAN CLI reads these
interactively or from its own encrypted local config — it does not require them to be
committed anywhere in this repo).

- [ ] **Step 4: Verify the connection**

Expected: the CLI reports a successful connection to Alpaca's paper endpoint and the
algorithm log shows `Initialize` completing without error. Full end-to-end verification
(actual `OnData` calls firing) can only be confirmed during real US market hours
(~9:30am–4:00pm ET, Mon–Fri) — if deployed outside those hours, connecting successfully
with no data yet flowing is the expected and correct state, not a failure.

- [ ] **Step 5: Commit**

```bash
git add .env.example graywind_strategy/config.json
git commit -m "chore: add Alpaca paper live-deploy config and credential documentation"
```

---

### Task 10: Burn-In Length Decision

**Files:**
- Create: `docs/superpowers/burn-in-decision.md`

**Interfaces:**
- Consumes: Task 8's real backtest statistics (Sharpe ratio, max drawdown, win rate) and
  Task 8's PDT-compliance result.
- Produces: a written, dated decision on how long Graywind paper-trades live before
  Phase 2 (ML) or Phase 3 (real capital) work begins — the spec requires this be an
  explicit decision, not silently skipped.

- [ ] **Step 1: Pull the real backtest numbers from Task 8's results JSON**

Run: `cat graywind_strategy/backtests/<timestamp>/*.json | grep -A5 '"Statistics"'`
(or open the file directly) — record the actual Sharpe Ratio, Drawdown, Win Rate, and
total number of trades produced by the Task 8 backtest.

- [ ] **Step 2: Write the decision doc**

Create `docs/superpowers/burn-in-decision.md`, filling in the real numbers from Step 1
(the template below shows the required structure — replace every bracketed value with
the actual backtest output, do not leave any bracket unfilled):

```markdown
# Graywind Phase 1 — Paper-Trading Burn-In Decision

**Date:** [today's date]

**Backtest results this decision is based on** (from `graywind_strategy/backtests/<timestamp>/`):
- Sharpe Ratio: [value]
- Max Drawdown: [value]
- Win Rate: [value]
- Total trades: [value]
- PDT compliance: [OK / VIOLATION — from Task 8 Step 5]

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
