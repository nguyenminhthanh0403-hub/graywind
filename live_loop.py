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
from graywind_strategy.dashboard_export import write_cycle_export
from graywind_strategy.state_store import load_state, save_state
from graywind_strategy.tier_config import SYMBOL_TIER
from graywind_strategy import volatility
from graywind_strategy.strategy_engine import compute_signals

WATCHLIST = ["AAPL", "SPY"]
DASHBOARD_EXPORT_DIR = "dashboard_export"
MARKET_OPEN = dt_time(9, 30)
MARKET_CLOSE = dt_time(16, 0)
ET = ZoneInfo("America/New_York")
# 21 calendar days of 15-min bars (up from 6, then 15): the original 6-day
# figure only needed to clear strategy_engine.compute_signals' own 30-bar
# indicator warm-up with a comfortable multi-session margin against
# weekend/holiday gaps (see below) -- volatility.confirmation_bars_series'
# real binding constraint is now the true minimum, NOT the 260-bar
# percentile window alone: compute_atr_pct burns ATR_PERIOD - 1 = 13
# leading bars on ATR warmup before the rolling 260-bar percentile window
# can even start counting toward its own PERCENTILE_WINDOW=260
# requirement, so the true minimum is
# volatility.ATR_PERIOD - 1 + volatility.PERCENTILE_WINDOW = 13 + 260 =
# 273 bars, not 260. A 15-day lookback was sized against the wrong (260)
# number and left thinner-tape symbols spending a meaningful fraction of
# cycles under 273 bars, silently pinning confirmation-bars to K=1
# (unfiltered). 21 calendar days is sized against the real 273-bar figure
# instead, with comfortable headroom (~2 more trading weeks) even across a
# long weekend, so the confirmation-bars filter actually leaves its K=1
# (unfiltered) fallback in live trading instead of running permanently
# unfiltered.
#
# Original 6-day reasoning, still true as a lower bound: worst case is a
# 3-day weekend+holiday gap (e.g. the Tuesday after MLK Monday, itself
# preceded by a weekend), which still needs to leave 2 full prior trading
# sessions (~52 bars at 26 bars/session) of headroom above the 30-bar
# warm-up strategy_engine.compute_signals requires before it computes a
# real signal (short-frame guard forces "hold" below that). A 3-day
# lookback only spans the tail of one session for most of a Monday
# (pinned at 27 bars all day -- never reaching 30) and the first
# post-holiday session (26 bars), silently forcing every "buy" evaluation
# to "hold" on those days -- indistinguishable in logs from a genuine
# no-signal bar. See final-review Fix 1.
SIGNAL_LOOKBACK = timedelta(days=21)


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


def reconcile_positions(trading_client, open_positions):
    """Reconcile local open_positions against Alpaca's real account state.
    Local state is authoritative for stop/target/entry_price (Alpaca's
    position API doesn't expose those), but Alpaca is authoritative for
    WHETHER a position exists. Logs loudly on any mismatch rather than
    guessing -- this bot never fabricates stop/target values for a
    position it didn't itself open.
    """
    real_positions = {p.symbol for p in trading_client.get_all_positions()}
    for symbol in list(open_positions.keys()):
        if symbol not in real_positions:
            print(f"{symbol}: WARNING - locally tracked position not found at broker, "
                  f"dropping from local state", file=sys.stderr)
            del open_positions[symbol]
    for symbol in real_positions:
        if symbol not in open_positions and symbol in WATCHLIST:
            print(f"{symbol}: WARNING - broker reports a position not tracked locally; "
                  f"not managed by this bot until resolved manually", file=sys.stderr)
    return open_positions


def process_symbol(symbol, signal, current_price, today, open_positions, equity,
                    pdt_throttle, position_sizer, drawdown_breaker_ok,
                    fred_api_key, news_client, finnhub_api_key, trading_client,
                    drawdown_breaker, cycle_timestamp=None, cycle_trades=None,
                    symbol_statuses=None, tier_pools=None):
    """Resolves one symbol's decision for this cycle: sell-on-stop/target
    exit if a held position crossed its stop or target, otherwise
    decide_trade() for a fresh entry -- but only if the symbol isn't
    already held (the skip-if-holding guard that keeps a sustained-uptrend
    "buy" signal from re-entering a position already open). Mutates
    `open_positions` in place (mirroring the backtester's own
    open_positions bookkeeping in graywind_strategy/backtester.py) and
    submits orders via `trading_client`; both are directly observable in
    tests via mocks, which is the point of extracting this out of main().

    `cycle_timestamp`/`cycle_trades`/`symbol_statuses` are optional
    dashboard-export collectors -- when omitted (None), no export data is
    recorded and behavior is identical to before this parameter existed,
    so every pre-existing caller/test needs no changes.

    `pending_same_day_trades` is computed from `open_positions` AFTER this
    symbol's own position (if any) has already been resolved/deleted above
    -- so it naturally excludes the symbol currently being evaluated,
    matching the "other symbols only" contract documented in
    pdt_throttle.py/pipeline.py, without needing an explicit exclusion.
    """
    if cycle_trades is None:
        cycle_trades = []
    if symbol_statuses is None:
        symbol_statuses = {}
    tier = SYMBOL_TIER.get(symbol)

    position = open_positions.get(symbol)
    if position is not None and (current_price <= position["stop"] or current_price >= position["target"]):
        order = MarketOrderRequest(
            symbol=symbol, qty=position["shares"],
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(order)
        if tier is not None and tier_pools is not None:
            tier_pools[tier] += position["shares"] * current_price
        cycle_trades.append({
            "timestamp": cycle_timestamp, "symbol": symbol, "side": "sell",
            "qty": position["shares"], "price": current_price, "reason": "stop/target exit",
        })
        # opened_date is stored/compared here as an ISO string (round-trips
        # through CSV via state_store.py); backtester.py's equivalent
        # comparison uses a `date` object instead since it never leaves
        # memory -- a future refactor unifying the two representations must
        # preserve each caller's own idiom.
        opened_date = datetime.fromisoformat(position["opened_date"]).date()
        if opened_date == today:
            pdt_throttle.record_day_trade(today)
        del open_positions[symbol]
        # Mirrors the backtester's per-exit update_equity call (see the
        # bar-by-bar loop in backtester.py) -- catches a same-cycle drawdown
        # breach triggered by this exit before evaluating later symbols in
        # this same cycle, rather than waiting for the next cycle's single
        # per-cycle update in main().
        drawdown_breaker.update_equity(equity)
        print(f"{symbol}: submitted sell for {position['shares']} shares (stop/target exit)")
        position = None  # eligible for a fresh same-cycle entry below, same as the backtester

    if position is None:
        if tier is not None and tier_pools is not None:
            committed = sum(
                p["entry_price"] * p["shares"] for s, p in open_positions.items()
                if SYMBOL_TIER.get(s) == tier
            )
            sizing_equity = tier_pools[tier] + committed
        else:
            sizing_equity = equity
        pending_today = sum(
            1 for p in open_positions.values() if p["opened_date"] == today.isoformat()
        )
        decision = decide_trade(
            symbol=symbol, signal=signal, as_of_date=today,
            current_price=current_price, account_equity=sizing_equity,
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
            if tier is not None and tier_pools is not None:
                tier_pools[tier] -= decision.shares * current_price
            open_positions[symbol] = {
                "entry_price": current_price, "shares": decision.shares,
                "stop": decision.stop_price, "target": decision.target_price,
                "opened_date": today.isoformat(),
            }
            cycle_trades.append({
                "timestamp": cycle_timestamp, "symbol": symbol, "side": "buy",
                "qty": decision.shares, "price": current_price, "reason": decision.reason,
            })
            symbol_statuses[symbol] = {
                "position_open": True, "shares": decision.shares, "entry_price": current_price,
                "current_price": current_price, "action": "buy", "reason": decision.reason,
            }
            print(f"{symbol}: submitted buy for {decision.shares} shares")
        else:
            symbol_statuses[symbol] = {
                "position_open": False, "shares": None, "entry_price": None,
                "current_price": current_price, "action": decision.action, "reason": decision.reason,
            }
            print(f"{symbol}: {decision.action} ({decision.reason})")
    else:
        symbol_statuses[symbol] = {
            "position_open": True, "shares": position["shares"], "entry_price": position["entry_price"],
            "current_price": current_price, "action": "hold",
            "reason": f"already holding {position['shares']} shares",
        }
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

    today = datetime.now(ET).date()
    cycle_timestamp = datetime.now(ET).isoformat()
    cycle_trades = []
    symbol_statuses = {}
    state = load_state()
    pdt_throttle = _restore_pdt_throttle(state)
    open_positions = state["open_positions"]
    open_positions = reconcile_positions(trading_client, open_positions)
    drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    position_sizer = PositionSizer()
    # Default to whatever was already persisted so the `finally` below has
    # something safe to write back even if get_account() itself raises
    # before a fresh starting_equity reading is ever computed -- in that
    # case there's nothing new to persist, so this is a no-op, not a crash
    # on an uninitialized variable.
    starting_equity = state["starting_equity"]
    equity = None
    # Only true once get_account() has actually succeeded and a real
    # starting_equity has been computed this cycle -- guards the `finally`
    # below from stamping today's date onto a stale (yesterday's, or
    # never-set) starting_equity. Without this, a failed get_account() on
    # the day's first cycle would still persist {"day": today, ...} paired
    # with the old starting_equity; the next cycle would see
    # state["day"] == today and treat that stale figure as already having
    # today's baseline, silently running DrawdownBreaker.start_new_day
    # against the wrong number for the rest of the day.
    baseline_established = False

    try:
        account = trading_client.get_account()
        equity = float(account.equity)
        starting_equity = state["starting_equity"] if state["day"] == today.isoformat() else equity
        baseline_established = True
        drawdown_breaker.start_new_day(today, starting_equity)
        drawdown_breaker.update_equity(equity)

        now = datetime.now(ET)
        for symbol in WATCHLIST:
            # A single symbol's failure (a transient network error fetching
            # bars, a gate's API call timing out, an order rejected by
            # Alpaca, etc.) must not prevent the remaining symbols in
            # WATCHLIST from being attempted this cycle -- routine for a
            # script making network calls every 15 minutes.
            try:
                bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
                if not bars:
                    print(f"{symbol}: no recent bars returned, skipping this cycle")
                    continue
                df = pd.DataFrame([
                    {"time": bar.timestamp, "close": bar.close,
                     "high": bar.high, "low": bar.low}
                    for bar in bars
                ])
                df = compute_signals(df, confirmation_bars=volatility.confirmation_bars_series(df))
                latest = df.iloc[-1]

                process_symbol(
                    symbol=symbol, signal=latest["signal"], current_price=latest["close"],
                    today=today, open_positions=open_positions, equity=equity,
                    pdt_throttle=pdt_throttle, position_sizer=position_sizer,
                    drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
                    fred_api_key=fred_api_key, news_client=news_client,
                    finnhub_api_key=finnhub_api_key, trading_client=trading_client,
                    drawdown_breaker=drawdown_breaker,
                    cycle_timestamp=cycle_timestamp, cycle_trades=cycle_trades,
                    symbol_statuses=symbol_statuses,
                )
            except Exception as exc:
                print(f"{symbol}: error processing this cycle, skipping: {exc}", file=sys.stderr)
    finally:
        # Must always run, with whatever confirmed progress (submitted
        # orders reflected in open_positions, recorded day-trades reflected
        # in pdt_throttle) was made before any exception -- otherwise a
        # buy that Alpaca already accepted goes untracked, and the next
        # cycle re-buys the same symbol on a still-"buy" trend signal with
        # its stop-loss never checked; on the sell side, a lost
        # record_day_trade call silently under-counts the PDT window
        # against the plan's 3-day-trade ceiling.
        save_state({
            "day_trade_dates": [d.isoformat() for d in pdt_throttle._day_trade_dates],
            # If get_account() failed and no fresh baseline was established
            # this cycle, leave "day"/"starting_equity" exactly as loaded --
            # never pair today's date with a stale or unset starting_equity.
            "day": today.isoformat() if baseline_established else state["day"],
            "starting_equity": starting_equity if baseline_established else state["starting_equity"],
            "open_positions": open_positions,
        })
        write_cycle_export(
            export_dir=DASHBOARD_EXPORT_DIR,
            timestamp=cycle_timestamp,
            symbols=WATCHLIST,
            equity=equity,
            today_pnl=(equity - starting_equity) if equity is not None and starting_equity else None,
            symbol_statuses=symbol_statuses,
            cycle_trades=cycle_trades,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
