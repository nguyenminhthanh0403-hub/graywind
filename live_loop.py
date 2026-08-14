#!/usr/bin/env python3
"""Single-shot live trading script: fetches the latest bar and gate data
for each symbol in the Phase 1 watchlist, checks any held position for a
stop/target exit, runs decide_trade() for symbols not currently held, and
places any resulting order against Alpaca's paper endpoint. Meant to be
invoked every 15 minutes by an external scheduler (cron/launchd) during
market hours only -- this script checks market hours itself and exits
early outside them, so it is safe to schedule unconditionally every 15
minutes around the clock.

Open positions and PDT/drawdown state are persisted to a local JSON file
(graywind_strategy/state_store.py) between invocations, since each run is
a fresh process rather than a long-running one -- state_store's
`open_positions` field is what lets this script (a) skip re-buying a
symbol it's already holding (the strategy signal is trend-state, not
crossover-only, so it re-emits "buy" on nearly every bar of a sustained
uptrend) and (b) know when a held position crosses its stop or target and
needs to be sold.

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


def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client):
    """Resolves one symbol's decision for this cycle: sell-on-stop/target
    exit if a held position crossed its stop or target, otherwise
    decide_trade() for a fresh entry -- but only if the symbol isn't
    already held (the skip-if-holding guard that keeps a sustained-uptrend
    "buy" signal from re-entering a position already open). Mutates
    `open_positions` in place (mirroring the backtester's own
    open_positions bookkeeping in graywind_strategy/backtester.py) and
    submits orders via `trading_client`; both are directly observable in
    tests via mocks, which is the point of extracting this out of main().

    `pending_same_day_trades` is computed from `open_positions` AFTER this
    symbol's own position (if any) has already been resolved/deleted above
    -- so it naturally excludes the symbol currently being evaluated,
    matching the "other symbols only" contract documented in
    pdt_throttle.py/pipeline.py, without needing an explicit exclusion.
    """
    position = open_positions.get(symbol)
    if position is not None and (current_price <= position["stop"] or current_price >= position["target"]):
        order = MarketOrderRequest(
            symbol=symbol, qty=position["shares"],
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(order)
        opened_date = datetime.fromisoformat(position["opened_date"]).date()
        if opened_date == today:
            pdt_throttle.record_day_trade(today)
        del open_positions[symbol]
        print(f"{symbol}: submitted sell for {position['shares']} shares (stop/target exit)")
        position = None  # eligible for a fresh same-cycle entry below, same as the backtester

    if position is None:
        pending_today = sum(
            1 for p in open_positions.values() if p["opened_date"] == today.isoformat()
        )
        decision = decide_trade(
            symbol=symbol, signal=signal, as_of_date=today,
            current_price=current_price, account_equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=position_sizer,
            drawdown_breaker_ok=drawdown_breaker_ok,
            fred_api_key=fred_api_key, news_client=news_client,
            finnhub_api_key=finnhub_api_key,
            pending_same_day_trades=pending_today,
        )
        if decision.action == "buy":
            order = MarketOrderRequest(
                symbol=symbol, qty=decision.shares,
                side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            trading_client.submit_order(order)
            open_positions[symbol] = {
                "entry_price": current_price, "shares": decision.shares,
                "stop": decision.stop_price, "target": decision.target_price,
                "opened_date": today.isoformat(),
            }
            print(f"{symbol}: submitted buy for {decision.shares} shares")
        else:
            print(f"{symbol}: {decision.action} ({decision.reason})")
    else:
        print(f"{symbol}: already holding {position['shares']} shares, skipping entry evaluation")


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
    open_positions = state["open_positions"]

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

        process_symbol(
            symbol=symbol, signal=latest["signal"], current_price=latest["close"],
            today=today, open_positions=open_positions, equity=equity,
            pdt_throttle=pdt_throttle, position_sizer=position_sizer,
            drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
            fred_api_key=fred_api_key, news_client=news_client,
            finnhub_api_key=finnhub_api_key, trading_client=trading_client,
        )

    save_state({
        "day_trade_dates": [d.isoformat() for d in pdt_throttle._day_trade_dates],
        "day": today.isoformat(),
        "starting_equity": starting_equity,
        "open_positions": open_positions,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
