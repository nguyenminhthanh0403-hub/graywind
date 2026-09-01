"""Composes the strategy signal, the four signal-augmentation gates, and
risk management into one order-eligibility decision. This is the single
code path both the backtester and the live loop call — keeping order logic
in one place is what guarantees backtest and live behavior can't drift
apart.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests

from graywind_strategy.gates.analyst_consensus import (
    AnalystDataUnavailable,
    analyst_consensus_multiplier,
    fetch_analyst_consensus,
    load_cached_multiplier,
    save_cached_multiplier,
)
from graywind_strategy.gates.earnings_gate import (
    EARNINGS_BLACKOUT_DAYS,
    EarningsDataUnavailable,
    earnings_gate,
    fetch_next_earnings_date,
)
from graywind_strategy.gate_result import GateResult
from graywind_strategy.gates.macro_gate import (
    MacroDataUnavailable, count_macro_breaches, fetch_bullion_macro_snapshot,
)
from graywind_strategy.gates.sector_gates import evaluate_sector_gates
from graywind_strategy.risk.position_sizing import QTY_DECIMALS
from graywind_strategy.gates.sentiment_gate import (
    SENTIMENT_THRESHOLD,
    SentimentDataUnavailable,
    fetch_recent_headlines,
    sentiment_gate,
    sentiment_score,
)
from graywind_strategy.gates.vix_gate import VIX_THRESHOLD, VixDataUnavailable, fetch_latest_vix, vix_gate

# The GateResult.detail emitted when the macro feed cannot answer, as opposed to
# answering "risk-off". Shared rather than a literal because three places must
# agree on it: pipeline.py writes it, live_loop.py maps it to the
# "unavailable" sentinel in decision_log.csv, and scripts/check_macro_health.py
# reads that sentinel to raise the macro alarm.
MACRO_UNAVAILABLE_DETAIL = "MacroDataUnavailable"


@dataclass
class TradeDecision:
    action: str  # "buy" | "hold" | "blocked"
    reason: str
    shares: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    gate_readings: list = field(default_factory=list)


def evaluate_vix_gate(fred_api_key, as_of_date=None, threshold=VIX_THRESHOLD):
    try:
        vix_value = fetch_latest_vix(fred_api_key, today=as_of_date)
    except VixDataUnavailable:
        return GateResult(passed=False, detail="VixDataUnavailable")
    return GateResult(passed=vix_gate(vix_value, threshold), value=vix_value)


def evaluate_sentiment_gate(news_client, symbol, as_of_date=None, threshold=SENTIMENT_THRESHOLD):
    try:
        headlines = fetch_recent_headlines(news_client, symbol, as_of=as_of_date)
    except SentimentDataUnavailable:
        return GateResult(passed=False, detail="SentimentDataUnavailable")
    score = sentiment_score(headlines)
    return GateResult(passed=sentiment_gate(score, threshold), value=score)


def evaluate_earnings_gate(symbol, finnhub_api_key, as_of_date, blackout_days=EARNINGS_BLACKOUT_DAYS):
    try:
        next_date = fetch_next_earnings_date(symbol, finnhub_api_key, as_of_date)
    except EarningsDataUnavailable:
        return GateResult(passed=False, detail="EarningsDataUnavailable")
    days_until = (next_date - as_of_date).days if next_date is not None else None
    return GateResult(passed=earnings_gate(next_date, as_of_date, blackout_days), value=days_until)


def evaluate_macro_gate(as_of_date, session=requests, required_breaches=2):
    try:
        snapshot = fetch_bullion_macro_snapshot(as_of_date, session=session)
    except MacroDataUnavailable:
        # NOTE this fails CLOSED: a macro feed that cannot answer blocks entries
        # exactly as a real risk-off reading does. That is the safe default, but
        # it means a dead upstream silently halts all trading, so the detail
        # string below is load-bearing -- live_loop logs it to decision_log.csv
        # and scripts/check_macro_health.py alarms on a sustained run of it.
        return GateResult(passed=False, detail=MACRO_UNAVAILABLE_DETAIL)
    breaches = count_macro_breaches(snapshot)
    return GateResult(passed=breaches < required_breaches, value=breaches)


def evaluate_analyst_consensus_multiplier(symbol, as_of_date, current_price):
    # `as_of_date` is computed by live_loop.py as datetime.now(ET).date() (Eastern
    # Time), but this guard compares it against date.today() (process-local
    # timezone). Safe by construction in production: GitHub Actions runs in
    # UTC, and the live-trading workflow's cron window only fires during
    # 09:30-16:00 ET, which is always the same UTC calendar day. This would
    # silently no-op the whole feature (not crash) if ever run from a
    # differently-timezoned environment during specific hours.
    if as_of_date != date.today():
        # yfinance has no historical point-in-time query -- applying it to a
        # backtest as_of_date would leak today's analyst opinions into a
        # historical decision. Neutral is the honest answer for any date
        # that isn't live "today".
        return 1.0

    cached = load_cached_multiplier(symbol, as_of_date)
    if cached is not None:
        return cached

    try:
        recommendation_mean, target_mean = fetch_analyst_consensus(symbol)
    except AnalystDataUnavailable:
        return 1.0

    multiplier = analyst_consensus_multiplier(recommendation_mean, target_mean, current_price)
    try:
        save_cached_multiplier(
            symbol, as_of_date,
            recommendation_mean=recommendation_mean, target_mean=target_mean, multiplier=multiplier,
        )
    except Exception:
        # Best-effort cache write -- a cache-write failure (disk full,
        # read-only filesystem, permissions) should cost this cycle's cache,
        # not the whole trade evaluation. decide_trade must never propagate
        # an exception.
        pass
    return multiplier


def decide_trade(symbol, signal, as_of_date, current_price, account_equity,
                  pdt_throttle, position_sizer, drawdown_breaker_ok: Optional[bool],
                  fred_api_key, news_client, finnhub_api_key,
                  pending_same_day_trades=0,
                  gates_always_pass=False,
                  stop_pct=0.02, take_profit_pct=0.03):
    """Decide whether to buy, hold, or block a trade for `symbol` as of `as_of_date`.

    `gates_always_pass`, when True, skips all five signal-augmentation
    gates (vix/sentiment/earnings/macro/sector) entirely -- the plan-specified,
    supported way to bypass them for testing/synthetic-data runs (e.g.
    scripts/task11_integration_run.py), instead of a caller monkeypatching
    this module's internals. Defaults to False so every existing call site
    is unaffected.

    `drawdown_breaker_ok` follows the same fail-closed contract as the three
    gates below: `True` means the caller confirmed the breaker is healthy;
    `False` OR `None` both block the trade. `None` means the caller could not
    determine the breaker's state (e.g. it hasn't been initialized for the
    day yet) -- that is treated identically to a confirmed-tripped breaker,
    never as "skip this check." Callers (the backtester in Task 11, the live
    loop in Task 12) must not pass `None` to mean "unknown, allow anyway."

    `pending_same_day_trades` is the count of *other* symbols' still-open
    positions opened earlier the same day (not including the symbol
    currently being evaluated) -- each one is a potential day trade that
    hasn't been realized yet. Forwarded straight into
    `pdt_throttle.can_open_day_trade` so the PDT check reserves a slot for
    at-risk positions, not just already-realized ones; without this, two
    symbols opened in the same session before either closes can each pass
    the realized-only check independently and both later close same-day,
    producing a real PDT violation neither individual check caught.

    `gate_readings` on the returned TradeDecision is the ordered list of
    GateResult objects (see graywind_strategy.gate_result) actually
    evaluated this call -- [vix, sentiment, earnings, macro, sector],
    truncated at whichever gate short-circuited the function. Stays empty
    when gates_always_pass=True or signal != "buy" (no gates were ever
    evaluated).
    """
    if signal != "buy":
        return TradeDecision(action="hold", reason="no buy signal")

    gate_readings = []
    if not gates_always_pass:
        # Called with keyword arguments (not positional) so that callers/tests
        # can swap these wrappers out for arbitrary-signature stand-ins (e.g.
        # `lambda **kw: True`) without needing to match positional arity.
        vix_result = evaluate_vix_gate(fred_api_key=fred_api_key, as_of_date=as_of_date)
        gate_readings.append(vix_result)
        if not vix_result:
            return TradeDecision(action="blocked", reason="vix_gate", gate_readings=gate_readings)
        sentiment_result = evaluate_sentiment_gate(news_client=news_client, symbol=symbol, as_of_date=as_of_date)
        gate_readings.append(sentiment_result)
        if not sentiment_result:
            return TradeDecision(action="blocked", reason="sentiment_gate", gate_readings=gate_readings)
        earnings_result = evaluate_earnings_gate(symbol=symbol, finnhub_api_key=finnhub_api_key, as_of_date=as_of_date)
        gate_readings.append(earnings_result)
        if not earnings_result:
            return TradeDecision(action="blocked", reason="earnings_gate", gate_readings=gate_readings)
        macro_result = evaluate_macro_gate(as_of_date=as_of_date)
        gate_readings.append(macro_result)
        if not macro_result:
            return TradeDecision(action="blocked", reason="macro_gate", gate_readings=gate_readings)
        sector_result = evaluate_sector_gates(symbol=symbol, as_of_date=as_of_date)
        gate_readings.append(sector_result)
        if not sector_result:
            return TradeDecision(action="blocked", reason="sector_gate", gate_readings=gate_readings)

    if not drawdown_breaker_ok:  # False or None both block -- fail closed on unknown state
        return TradeDecision(action="blocked", reason="drawdown_breaker", gate_readings=gate_readings)
    if not pdt_throttle.can_open_day_trade(as_of_date, pending_count=pending_same_day_trades):
        return TradeDecision(action="blocked", reason="pdt_throttle", gate_readings=gate_readings)

    stop_price = position_sizer.stop_loss_price(current_price, stop_pct)
    if current_price <= 0 or stop_price >= current_price:
        # A near-zero or non-positive price makes the rounded 2% stop land on
        # or above entry -- shares_to_buy would raise ValueError. decide_trade
        # is the single order-eligibility path for both backtest and live, so
        # it must never propagate an exception; fail to "hold", not a crash.
        return TradeDecision(action="hold", reason="invalid price for sizing", gate_readings=gate_readings)
    target_price = position_sizer.take_profit_price(current_price, take_profit_pct)
    shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
    shares = round(shares * evaluate_analyst_consensus_multiplier(
        symbol=symbol, as_of_date=as_of_date, current_price=current_price), QTY_DECIMALS)
    if shares <= 0:
        return TradeDecision(action="hold", reason="position size rounds to zero shares", gate_readings=gate_readings)

    return TradeDecision(
        action="buy", reason="all checks passed",
        shares=shares, stop_price=stop_price, target_price=target_price,
        gate_readings=gate_readings,
    )
