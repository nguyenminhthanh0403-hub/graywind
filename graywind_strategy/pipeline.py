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


def evaluate_vix_gate(fred_api_key, as_of_date=None, threshold=VIX_THRESHOLD):
    try:
        vix_value = fetch_latest_vix(fred_api_key, today=as_of_date)
    except VixDataUnavailable:
        return False
    return vix_gate(vix_value, threshold)


def evaluate_sentiment_gate(news_client, symbol, as_of_date=None, threshold=SENTIMENT_THRESHOLD):
    try:
        headlines = fetch_recent_headlines(news_client, symbol, as_of=as_of_date)
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
                  pdt_throttle, position_sizer, drawdown_breaker_ok: Optional[bool],
                  fred_api_key, news_client, finnhub_api_key,
                  stop_pct=0.02, take_profit_pct=0.03):
    """Decide whether to buy, hold, or block a trade for `symbol` as of `as_of_date`.

    `drawdown_breaker_ok` follows the same fail-closed contract as the three
    gates below: `True` means the caller confirmed the breaker is healthy;
    `False` OR `None` both block the trade. `None` means the caller could not
    determine the breaker's state (e.g. it hasn't been initialized for the
    day yet) -- that is treated identically to a confirmed-tripped breaker,
    never as "skip this check." Callers (the backtester in Task 11, the live
    loop in Task 12) must not pass `None` to mean "unknown, allow anyway."
    """
    if signal != "buy":
        return TradeDecision(action="hold", reason="no buy signal")

    # Called with keyword arguments (not positional) so that callers/tests
    # can swap these wrappers out for arbitrary-signature stand-ins (e.g.
    # `lambda **kw: True`) without needing to match positional arity.
    if not evaluate_vix_gate(fred_api_key=fred_api_key, as_of_date=as_of_date):
        return TradeDecision(action="blocked", reason="vix_gate")
    if not evaluate_sentiment_gate(news_client=news_client, symbol=symbol, as_of_date=as_of_date):
        return TradeDecision(action="blocked", reason="sentiment_gate")
    if not evaluate_earnings_gate(symbol=symbol, finnhub_api_key=finnhub_api_key, as_of_date=as_of_date):
        return TradeDecision(action="blocked", reason="earnings_gate")

    if not drawdown_breaker_ok:  # False or None both block -- fail closed on unknown state
        return TradeDecision(action="blocked", reason="drawdown_breaker")
    if not pdt_throttle.can_open_day_trade(as_of_date):
        return TradeDecision(action="blocked", reason="pdt_throttle")

    stop_price = position_sizer.stop_loss_price(current_price, stop_pct)
    if current_price <= 0 or stop_price >= current_price:
        # A near-zero or non-positive price makes the rounded 2% stop land on
        # or above entry -- shares_to_buy would raise ValueError. decide_trade
        # is the single order-eligibility path for both backtest and live, so
        # it must never propagate an exception; fail to "hold", not a crash.
        return TradeDecision(action="hold", reason="invalid price for sizing")
    target_price = position_sizer.take_profit_price(current_price, take_profit_pct)
    shares = position_sizer.shares_to_buy(account_equity, current_price, stop_price)
    if shares <= 0:
        return TradeDecision(action="hold", reason="position size rounds to zero shares")

    return TradeDecision(
        action="buy", reason="all checks passed",
        shares=shares, stop_price=stop_price, target_price=target_price,
    )
