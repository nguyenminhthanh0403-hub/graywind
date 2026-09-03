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
in the environment. See .env.example. DEEPSEEK_API_KEY is optional -- when
unset, `llm_client` stays None and only the shadow-mode news-debate logging
(news_debate_log.csv) is disabled; the rest of the trading cycle (real
gates, sizing, order submission) is completely unaffected.
"""
import os
import sys
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo

import openai
import pandas as pd
import requests
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.news import NewsClient
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from fetch_alpaca_data import fetch_bars
from graywind_strategy.pipeline import MACRO_UNAVAILABLE_DETAIL, decide_trade
from graywind_strategy.risk.drawdown_breaker import (
    DrawdownBreaker, build_rolling_breakers, widest_history,
)
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.gates.news_debate import evaluate_shadow_debate
from graywind_strategy import trade_approval
from graywind_strategy.dashboard_export import write_cycle_export, log_news_debate
from graywind_strategy.state_store import (
    append_decision_log, load_state, save_state, load_tier_pools, save_tier_pools,
    load_rebalance_state, save_rebalance_state, load_equity_history, save_equity_history,
    load_pending_trades, save_pending_trades,
)
from graywind_strategy.tier_config import SYMBOL_TIER, TIER1_SYMBOL_WEIGHTS
from graywind_strategy.tier1_rebalance import compute_rebalance_orders, should_rebalance_this_month
from graywind_strategy import volatility
from graywind_strategy.strategy_engine import compute_signals

WATCHLIST = ["AAPL", "SERV"]
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

DECISION_GATE_ORDER = ["vix", "sentiment", "earnings", "macro", "sector"]

# What decision_log.csv's macro_breaches column holds when the macro feed could
# not answer at all (as opposed to a breach count). scripts/check_macro_health.py
# reads this exact string.
MACRO_UNAVAILABLE_SENTINEL = "unavailable"


def _fmt_decision_value(value):
    return "" if value is None else str(value)


def _fmt_earnings_value(value, reached):
    # evaluate_earnings_gate (pipeline.py) legitimately returns value=None
    # when it actually ran and found no earnings scheduled -- a real,
    # meaningful reading. That's indistinguishable from `earnings` never
    # having run at all (an earlier gate in DECISION_GATE_ORDER
    # short-circuited first) once both collapse to the same blank ""
    # through _fmt_decision_value. Final-review finding I5: emit a distinct
    # sentinel ("none") for the genuinely-evaluated case so the two
    # situations are no longer indistinguishable in decision_log.csv.
    # GateResult/pipeline.py are unchanged -- this is purely a live_loop.py
    # CSV-formatting distinction.
    if not reached:
        return ""
    return "none" if value is None else str(value)


def _fmt_macro_value(value, reached, detail):
    # Same shape of ambiguity as _fmt_earnings_value above. evaluate_macro_gate
    # returns value=None with detail="MacroDataUnavailable" when the upstream
    # Bullion feed cannot answer, which collapsed to "" through
    # _fmt_decision_value -- indistinguishable from the macro gate never having
    # run because an earlier gate short-circuited. Since the gate fails CLOSED,
    # that made a dead upstream (which silently halts ALL entries indefinitely)
    # look identical in decision_log.csv to a routine short-circuit. Emit a
    # distinct sentinel so scripts/check_macro_health.py can alarm on it.
    if not reached:
        return ""
    if detail == MACRO_UNAVAILABLE_DETAIL:
        return MACRO_UNAVAILABLE_SENTINEL
    return _fmt_decision_value(value)


def _decision_log_row(cycle_timestamp, symbol, decision, rsi, sma_fast, sma_slow):
    gate_values = {name: None for name in DECISION_GATE_ORDER}
    gate_details = {name: "" for name in DECISION_GATE_ORDER}
    reached_gates = set()
    for name, result in zip(DECISION_GATE_ORDER, decision.gate_readings):
        gate_values[name] = result.value
        gate_details[name] = result.detail
        reached_gates.add(name)
    return {
        "timestamp": cycle_timestamp,
        "symbol": symbol,
        "action": decision.action,
        "reason": decision.reason,
        "rsi": _fmt_decision_value(rsi),
        "sma_fast": _fmt_decision_value(sma_fast),
        "sma_slow": _fmt_decision_value(sma_slow),
        "vix": _fmt_decision_value(gate_values["vix"]),
        "sentiment": _fmt_decision_value(gate_values["sentiment"]),
        "days_to_earnings": _fmt_earnings_value(gate_values["earnings"], "earnings" in reached_gates),
        "macro_breaches": _fmt_macro_value(
            gate_values["macro"], "macro" in reached_gates, gate_details["macro"],
        ),
        "sector_gates": _fmt_decision_value(gate_values["sector"]),
    }


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
                    symbol_statuses=None, tier_pools=None,
                    rsi=None, sma_fast=None, sma_slow=None, decision_rows=None,
                    llm_client=None, debate_cache=None, debate_rows=None,
                    pending_trades=None, github_token=None, repo=None,
                    account_label=None, session=requests):
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

    `llm_client`/`debate_cache`/`debate_rows` are the shadow-mode
    news-debate collectors -- when `llm_client` is None (the
    DEEPSEEK_API_KEY-not-set case), the debate step is skipped entirely,
    identical to behavior before these parameters existed. When given,
    a debate-call failure (network, malformed structured output) is caught
    here and never propagates or affects the real buy/sell/hold decision
    above -- shadow mode fails open, the opposite of every real gate in
    this file. Runs only in the same branch as the real decide_trade()
    call (mirrors "alongside the existing news_client usage" -- an
    already-held position never reaches this branch and is never debated
    either, matching decide_trade()'s own skip-if-holding scope), but
    independently of decide_trade()'s own signal/gate short-circuiting --
    it always fetches and scores headlines when reached, so the shadow log
    accumulates a verdict for every symbol/cycle this branch runs, not
    just the subset where VADER's gate happened to run live. Deliberately
    positioned AFTER decide_trade() and the resulting buy/hold handling
    (rather than before it) so that a slow or hung debate call can never
    delay real order submission -- see final-review Fix 3.
    """
    if cycle_trades is None:
        cycle_trades = []
    if symbol_statuses is None:
        symbol_statuses = {}
    if pending_trades is None:
        pending_trades = {}
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
        if decision_rows is not None:
            decision_rows.append(_decision_log_row(
                cycle_timestamp=cycle_timestamp, symbol=symbol, decision=decision,
                rsi=rsi, sma_fast=sma_fast, sma_slow=sma_slow,
            ))
        if decision.action == "buy":
            if tier is None:
                # Restores the semantics the pre-approval direct-execution code
                # had via its own `tier is not None` guard (still visible on the
                # sell path above). A symbol on WATCHLIST but missing from
                # SYMBOL_TIER would otherwise be proposed with tier=None, which
                # round-trips through pending_trades.csv as None and then
                # KeyErrors on `tier_pools[None]` at execution time -- AFTER the
                # order is submitted -- leaving the row in place to be
                # resubmitted every cycle. It would also create a GitHub issue
                # labelled literally "tier:None". tier_config.py calls
                # SYMBOL_TIER "a living list", so refusing here is what keeps
                # the next watchlist addition from arming that loop.
                symbol_statuses[symbol] = {
                    "position_open": False, "shares": None, "entry_price": None,
                    "current_price": current_price, "action": "skipped",
                    "reason": "symbol has no tier in SYMBOL_TIER; not proposing a buy",
                }
                print(f"{symbol}: buy signal but symbol has no tier in SYMBOL_TIER, "
                      f"refusing to propose", file=sys.stderr)
            elif symbol in pending_trades:
                symbol_statuses[symbol] = {
                    "position_open": False, "shares": None, "entry_price": None,
                    "current_price": current_price, "action": "pending",
                    "reason": "awaiting approval on existing proposal",
                }
                print(f"{symbol}: already has a pending trade proposal, skipping")
            else:
                issue_number = trade_approval.propose_trade(
                    symbol=symbol, side="buy", qty=decision.shares, price=current_price,
                    tier=tier, account_label=account_label, reasoning=decision.reason,
                    github_token=github_token, repo=repo, session=session,
                )
                pending_trades[symbol] = {
                    "issue_number": issue_number, "side": "buy", "qty": decision.shares,
                    "price_at_proposal": current_price, "stop_price": decision.stop_price,
                    "target_price": decision.target_price, "tier": tier,
                    "proposed_date": today.isoformat(),
                }
                symbol_statuses[symbol] = {
                    "position_open": False, "shares": None, "entry_price": None,
                    "current_price": current_price, "action": "proposed", "reason": decision.reason,
                }
                print(f"{symbol}: proposed buy for {decision.shares} shares (issue #{issue_number}), awaiting approval")
        else:
            symbol_statuses[symbol] = {
                "position_open": False, "shares": None, "entry_price": None,
                "current_price": current_price, "action": decision.action, "reason": decision.reason,
            }
            print(f"{symbol}: {decision.action} ({decision.reason})")

        # Runs AFTER the buy/hold handling above (and thus after
        # decide_trade()/order submission) so that a slow or hung DeepSeek
        # endpoint never delays real order placement -- delaying WHEN the
        # real decision executes is itself an effect on the trade cycle the
        # spec says shadow mode must never have, even though it never
        # touches the decision itself. Still scoped to `if position is
        # None:` only (an already-held position is never debated -- see
        # final-review controller ruling deferring that as a separate
        # scope decision). See final-review Fix 3.
        if llm_client is not None:
            try:
                debate_result = evaluate_shadow_debate(
                    llm_client=llm_client, news_client=news_client, symbol=symbol,
                    as_of_date=today, cache=debate_cache if debate_cache is not None else {},
                )
                if debate_rows is not None:
                    debate_rows.append({
                        "timestamp": cycle_timestamp, "symbol": symbol, **debate_result,
                    })
            except Exception as exc:
                print(f"{symbol}: news debate shadow-mode error, skipping this cycle's row: {exc}",
                      file=sys.stderr)
    else:
        symbol_statuses[symbol] = {
            "position_open": True, "shares": position["shares"], "entry_price": position["entry_price"],
            "current_price": current_price, "action": "hold",
            "reason": f"already holding {position['shares']} shares",
        }
        print(f"{symbol}: already holding {position['shares']} shares, skipping entry evaluation")


def run_tier1_rebalance(trading_client, data_client, tier_pools, pending_trades=None,
                         github_token=None, repo=None, account_label=None, today=None,
                         session=requests):
    """I/O wrapper around tier1_rebalance.compute_rebalance_orders(): fetches
    each tier-1 symbol's latest bar and Alpaca's real current holdings,
    computes the rebalance orders, and settles them -- sells execute
    immediately (risk-reducing, stays automatic); buys are proposed via a
    GitHub issue instead of submitted directly (docs/superpowers/specs/
    2026-08-26-graywind-trade-approval-advisor-design.md). No-ops entirely
    (zero I/O) when TIER1_SYMBOL_WEIGHTS is empty -- see tier_config.py.
    """
    if not TIER1_SYMBOL_WEIGHTS:
        return []
    pending_trades = {} if pending_trades is None else pending_trades
    if today is None:
        today = datetime.now(ET).date()

    now = datetime.now(ET)
    current_prices = {}
    for symbol in TIER1_SYMBOL_WEIGHTS:
        bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
        if bars:
            current_prices[symbol] = bars[-1].close

    real_positions = {p.symbol: float(p.qty) for p in trading_client.get_all_positions()}
    current_holdings = {symbol: real_positions.get(symbol, 0.0) for symbol in TIER1_SYMBOL_WEIGHTS}

    tier1_equity = tier_pools[1] + sum(
        current_holdings[s] * current_prices[s] for s in current_holdings if s in current_prices
    )
    orders = compute_rebalance_orders(
        tier1_equity=tier1_equity, current_holdings=current_holdings,
        current_prices=current_prices, target_weights=TIER1_SYMBOL_WEIGHTS,
    )
    for order in orders:
        if order.side == "buy":
            if order.symbol in pending_trades:
                print(f"{order.symbol}: already has a pending trade proposal, skipping rebalance buy")
                continue
            issue_number = trade_approval.propose_trade(
                symbol=order.symbol, side="buy", qty=order.qty, price=current_prices[order.symbol],
                tier=1, account_label=account_label, reasoning="tier-1 monthly drift rebalance",
                github_token=github_token, repo=repo, session=session,
            )
            pending_trades[order.symbol] = {
                "issue_number": issue_number, "side": "buy", "qty": order.qty,
                "price_at_proposal": current_prices[order.symbol], "stop_price": None,
                "target_price": None, "tier": 1, "proposed_date": today.isoformat(),
            }
            print(f"{order.symbol}: proposed tier-1 rebalance buy for {order.qty} shares (issue #{issue_number})")
            continue
        market_order = MarketOrderRequest(
            symbol=order.symbol, qty=order.qty,
            side=OrderSide.SELL, time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(market_order)
        notional = order.qty * current_prices[order.symbol]
        tier_pools[1] += notional
        print(f"{order.symbol}: submitted tier-1 rebalance sell for {order.qty} shares")
    return orders


PRICE_STALENESS_TOLERANCE = 0.02


def process_pending_trades(pending_trades, today, trading_client, drawdown_breaker,
                            github_token, repo, owner_username, tier_pools, open_positions,
                            data_client, cycle_trades=None, symbol_statuses=None, session=requests,
                            rolling_breakers=()):
    """Resolves every open trade-approval proposal once per cycle: expires a
    stale (not-today) proposal, closes a rejected one, executes an approved
    one only after re-validating price/drawdown/position-not-already-open
    against fresh current state (time has passed since the proposal was
    created). One symbol's API failure must not block resolving the others
    this cycle -- same fail-isolation convention as the WATCHLIST loop in
    main().

    `rolling_breakers` mirrors main()'s own weekly/monthly breakers list
    (each with a `.can_open_new_trade()` method) -- the proposal-creation
    gate in main() requires the daily breaker AND every rolling breaker to
    allow a new trade, so re-validation at approval time (after time has
    passed since the proposal) must apply the same combined gate, not just
    the daily one. Defaults to `()` so `all(...)` over an empty sequence is
    permissively True, matching every pre-existing caller/test that doesn't
    pass rolling breakers at all.
    """
    if cycle_trades is None:
        cycle_trades = []
    if symbol_statuses is None:
        symbol_statuses = {}

    for symbol in list(pending_trades.keys()):
        trade = pending_trades[symbol]
        try:
            if trade["proposed_date"] != today.isoformat():
                # Expiring a proposal is local bookkeeping; it must not be gated
                # on GitHub accepting the closing comment. If the issue was
                # deleted or transferred out-of-band, close_issue 404s forever,
                # and because duplicate-proposal suppression in process_symbol
                # and run_tier1_rebalance is keyed on `symbol in
                # pending_trades`, an undeletable row is a permanent, silent,
                # per-symbol outage. Close best-effort, delete unconditionally.
                try:
                    trade_approval.close_issue(
                        trade["issue_number"], "expired -- no decision by end of trading day.",
                        github_token, repo, session=session,
                    )
                except Exception as exc:
                    print(f"{symbol}: expiring proposal but failed to close GitHub issue "
                          f"#{trade['issue_number']}: {exc}", file=sys.stderr)
                del pending_trades[symbol]
                continue

            try:
                decision = trade_approval.get_owner_reaction(
                    trade["issue_number"], owner_username, github_token, repo, session=session,
                )
            except trade_approval.IssueNotFound:
                del pending_trades[symbol]
                continue

            if decision == "rejected":
                trade_approval.close_issue(
                    trade["issue_number"], "rejected.", github_token, repo, session=session,
                )
                del pending_trades[symbol]
                continue

            if decision != "approved":
                continue  # still waiting, leave it open

            now = datetime.now(ET)
            bars = fetch_bars(data_client, symbol, now - SIGNAL_LOOKBACK, now)
            if not bars:
                continue  # can't re-validate without a current price -- try again next cycle
            current_price = bars[-1].close
            price_drift = abs(current_price - trade["price_at_proposal"]) / trade["price_at_proposal"]

            failure_reason = None
            if price_drift > PRICE_STALENESS_TOLERANCE:
                failure_reason = (
                    f"price moved {price_drift:.1%} since proposal, "
                    f"exceeding {PRICE_STALENESS_TOLERANCE:.0%} tolerance"
                )
            elif not drawdown_breaker.can_open_new_trade():
                failure_reason = "drawdown breaker no longer allows new trades"
            elif not all(b.can_open_new_trade() for b in rolling_breakers):
                failure_reason = "rolling drawdown breaker no longer allows new trades"
            elif symbol in open_positions:
                failure_reason = "position already opened since this proposal was made"
            elif trade["tier"] not in tier_pools:
                # Companion to process_symbol's tier=None refusal: a row
                # persisted by an earlier build (or a hand-edited
                # pending_trades.csv) can still carry a tier that isn't a
                # tier_pools key. Debiting it raises KeyError, and that raise
                # would land AFTER submit_order -- so catch it here, before any
                # order goes out, rather than submitting and then crashing.
                failure_reason = f"tier {trade['tier']!r} has no capital pool; cannot settle this buy"

            if failure_reason is not None:
                trade_approval.close_issue(
                    trade["issue_number"], f"not executed: {failure_reason}.", github_token, repo, session=session,
                )
                del pending_trades[symbol]
                continue

            order = MarketOrderRequest(
                symbol=symbol, qty=trade["qty"], side=OrderSide.BUY, time_in_force=TimeInForce.DAY,
            )
            trading_client.submit_order(order)
            # Dropped from pending_trades the instant the order is real, BEFORE
            # the tier_pools debit, the open_positions/symbol_statuses updates
            # and close_issue. Any exception in that tail is swallowed by the
            # outer per-symbol except, so leaving the row in place would let the
            # next cycle re-validate it clean and submit the SAME order again,
            # every cycle, until the price drifts past
            # PRICE_STALENESS_TOLERANCE or the day ends. `trade` is a local
            # reference to the same dict, so everything below still reads the
            # proposal's fields normally. Closing the GitHub issue is
            # best-effort bookkeeping, not a gate on whether the trade is
            # considered resolved -- same reasoning, applied one step earlier.
            del pending_trades[symbol]
            tier_pools[trade["tier"]] -= trade["qty"] * current_price
            if trade["tier"] != 1:
                open_positions[symbol] = {
                    "entry_price": current_price, "shares": trade["qty"],
                    "stop": trade["stop_price"], "target": trade["target_price"],
                    "opened_date": today.isoformat(),
                }
                symbol_statuses[symbol] = {
                    "position_open": True, "shares": trade["qty"], "entry_price": current_price,
                    "current_price": current_price, "action": "buy", "reason": "approved via GitHub issue",
                }
            cycle_trades.append({
                "timestamp": now.isoformat(), "symbol": symbol, "side": "buy",
                "qty": trade["qty"], "price": current_price, "reason": "approved via GitHub issue",
            })
            print(f"{symbol}: executed approved buy for {trade['qty']} shares")
            try:
                trade_approval.close_issue(
                    trade["issue_number"],
                    f"approved and executed: bought {trade['qty']} shares at ~{current_price}.",
                    github_token, repo, session=session,
                )
            except Exception as exc:
                print(f"{symbol}: order executed but failed to close GitHub issue "
                      f"#{trade['issue_number']}: {exc}", file=sys.stderr)
        except Exception as exc:
            # Backstop for the property the expiry branch above already
            # guarantees on its own path: whatever raises while resolving a
            # symbol, a row that is not from TODAY must never survive the
            # cycle. A row that can never be deleted is a permanent, silent,
            # per-symbol outage, since duplicate-proposal suppression in
            # process_symbol/run_tier1_rebalance is keyed on
            # `symbol in pending_trades`. Today's rows are still retried next
            # cycle as before -- only a stale one is force-dropped, and the
            # drop itself does no I/O so it cannot raise again.
            stale = pending_trades.get(symbol)
            if stale is not None and stale.get("proposed_date") != today.isoformat():
                del pending_trades[symbol]
                print(f"{symbol}: error resolving pending trade proposed "
                      f"{stale.get('proposed_date')!r}; force-dropping the stale row: {exc}",
                      file=sys.stderr)
            else:
                print(f"{symbol}: error resolving pending trade, will retry next cycle: {exc}",
                      file=sys.stderr)


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
    deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner_username = repo.split("/")[0] if repo else ""

    state_dir = os.environ.get("GRAYWIND_STATE_DIR", "state")
    dashboard_dir = os.environ.get("GRAYWIND_DASHBOARD_DIR", "dashboard-data")
    account_label = "small" if state_dir == "state/small" else "100k"

    trading_client = TradingClient(api_key, api_secret, paper=True)
    data_client = StockHistoricalDataClient(api_key, api_secret)
    news_client = NewsClient(api_key, api_secret)
    # timeout/max_retries bounded explicitly: the SDK's own defaults (10min
    # timeout, 2 retries) could otherwise stall a cycle for up to ~30min on
    # a hung endpoint. This is a shadow-mode call that must never
    # meaningfully delay real order submission -- see final-review Fix 3.
    llm_client = (
        openai.OpenAI(
            api_key=deepseek_api_key, base_url="https://api.deepseek.com",
            timeout=20.0, max_retries=1,
        )
        if deepseek_api_key else None
    )

    today = datetime.now(ET).date()
    cycle_timestamp = datetime.now(ET).isoformat()
    cycle_trades = []
    symbol_statuses = {}
    decision_rows = []
    debate_cache = {}
    debate_rows = []
    state = load_state(state_dir=state_dir)
    pending_trades = load_pending_trades(state_dir=state_dir)
    tier_pools = load_tier_pools(state_dir=state_dir)
    rebalance_state = load_rebalance_state(state_dir=state_dir)
    pdt_throttle = _restore_pdt_throttle(state)
    open_positions = state["open_positions"]
    open_positions = reconcile_positions(trading_client, open_positions)
    drawdown_breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    # Rolling (weekly/monthly) breakers above the daily one: they catch the slow
    # bleed a per-day limit structurally cannot see. Seeded from persisted
    # history, which is empty on the first cycle after deploy -- the breakers are
    # permissive on thin history by design, so that cold start does not halt
    # live trading (see risk/drawdown_breaker.py).
    rolling_breakers = build_rolling_breakers()
    equity_history = load_equity_history(state_dir=state_dir)
    for breaker in rolling_breakers:
        breaker.load_history(equity_history)
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
        # Guarded exactly as backtester.py does: record_equity rejects
        # non-positive equity, and this sits above the WATCHLIST loop with no
        # `except` between it and the cycle body. An unguarded raise on a wiped-out
        # or margin-debit account would abandon the whole cycle *including the
        # stop/target exit checks*, leaving positions past their stop open -- the
        # exact scenario where exits matter most.
        if equity > 0:
            for breaker in rolling_breakers:
                breaker.record_equity(today, equity)

        # Placed AFTER the record_equity loop above (not before it): an
        # approved trade's re-validation must weigh the rolling breakers
        # against TODAY's equity, not against whatever history was loaded
        # before this cycle recorded a fresh reading. Runs unconditionally
        # regardless of the `equity > 0` guard above (it sits outside that
        # `if`), same as the WATCHLIST loop below -- a proposal still needs
        # to be expired/rejected/resolved even on a wiped-out-equity cycle.
        process_pending_trades(
            pending_trades, today, trading_client, drawdown_breaker, github_token, repo,
            owner_username, tier_pools, open_positions, data_client,
            cycle_trades=cycle_trades, symbol_statuses=symbol_statuses,
            rolling_breakers=rolling_breakers,
        )

        if should_rebalance_this_month(rebalance_state["last_rebalance_month"], today):
            try:
                orders = run_tier1_rebalance(
                    trading_client, data_client, tier_pools, pending_trades=pending_trades,
                    github_token=github_token, repo=repo, account_label=account_label, today=today,
                )
                # Rebalance buys are now only PROPOSED, not executed. Stamping
                # the month regardless would mean an unapproved proposal that
                # expires at end of day silently skips tier 1's drift
                # correction for a WHOLE month, since should_rebalance_this_month
                # won't fire again until the next one. Only stamp once no buy
                # this rebalance wanted is still sitting unresolved in
                # pending_trades -- which covers both a freshly-created proposal
                # and one this call skipped because the symbol was already
                # pending. Sells (risk-reducing, still immediate) and an empty
                # order list stamp normally.
                unresolved_buys = [
                    o.symbol for o in orders if o.side == "buy" and o.symbol in pending_trades
                ]
                if unresolved_buys:
                    print(f"tier1 rebalance: buy proposals awaiting approval "
                          f"({', '.join(unresolved_buys)}); not marking this month done yet")
                else:
                    rebalance_state["last_rebalance_month"] = today.strftime("%Y-%m")
            except Exception as exc:
                print(f"tier1 rebalance: error, will retry next cycle: {exc}", file=sys.stderr)

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
                    drawdown_breaker_ok=(
                        drawdown_breaker.can_open_new_trade()
                        and all(b.can_open_new_trade() for b in rolling_breakers)
                    ),
                    fred_api_key=fred_api_key, news_client=news_client,
                    finnhub_api_key=finnhub_api_key, trading_client=trading_client,
                    drawdown_breaker=drawdown_breaker,
                    cycle_timestamp=cycle_timestamp, cycle_trades=cycle_trades,
                    symbol_statuses=symbol_statuses, tier_pools=tier_pools,
                    rsi=latest["rsi"], sma_fast=latest["sma_fast"], sma_slow=latest["sma_slow"],
                    decision_rows=decision_rows,
                    llm_client=llm_client, debate_cache=debate_cache, debate_rows=debate_rows,
                    pending_trades=pending_trades, github_token=github_token, repo=repo,
                    account_label=account_label,
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
        }, state_dir=state_dir)
        save_tier_pools(tier_pools, state_dir=state_dir)
        save_rebalance_state(rebalance_state, state_dir=state_dir)
        save_pending_trades(pending_trades, state_dir=state_dir)
        # Persist the longest window's rows (a superset of the shorter ones).
        # If get_account() failed this cycle nothing was recorded, so this
        # writes back what was loaded -- idempotent, never a data loss.
        save_equity_history(widest_history(rolling_breakers), state_dir=state_dir)
        append_decision_log(decision_rows, state_dir=state_dir)
        write_cycle_export(
            export_dir=DASHBOARD_EXPORT_DIR,
            timestamp=cycle_timestamp,
            symbols=WATCHLIST,
            equity=equity,
            today_pnl=(equity - starting_equity) if equity is not None and starting_equity else None,
            symbol_statuses=symbol_statuses,
            cycle_trades=cycle_trades,
        )
        # Guarded and run AFTER write_cycle_export: a shadow-mode logging
        # failure here (schema mismatch, disk/permission error) must never
        # prevent the real dashboard export above from running, nor
        # propagate out of main() and fail the whole job -- fails open, per
        # the spec's mandate that shadow mode never affects the rest of the
        # cycle. See final-review Fix 2.
        try:
            log_news_debate(debate_rows, dashboard_dir=dashboard_dir)
        except Exception as exc:
            print(f"news debate log write failed, skipping: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
