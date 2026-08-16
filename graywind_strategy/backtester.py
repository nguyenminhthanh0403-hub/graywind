"""Hand-rolled bar-by-bar backtester: replays decide_trade() over historical
data for each symbol independently, then computes Sharpe ratio, max
drawdown, and win rate from the resulting equity curve and trade log.
Also verifies no rolling 5-business-day window in the backtest period ever
exceeded 3 day-trades — the PDT throttle checked against real historical
simulation, not just trusted from code review.
"""
import statistics
from dataclasses import dataclass, field
from itertools import groupby

from graywind_strategy.pipeline import decide_trade
from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker
from graywind_strategy.risk.pdt_throttle import PDTThrottle
from graywind_strategy.risk.position_sizing import PositionSizer
from graywind_strategy.strategy_engine import compute_signals

# This project's bars are always 15-minute, ~6.5-hour-session bars (Task 5's
# fetch format). sharpe_ratio's own default (periods_per_year=252) assumes
# one bar per trading day; annualizing 15-minute bars with that default
# understates Sharpe by roughly sqrt(BARS_PER_TRADING_DAY_15MIN). Kept as a
# module-level constant here (not a change to sharpe_ratio's default) since
# sharpe_ratio is a general-purpose function other callers might use with
# different bar sizes.
BARS_PER_TRADING_DAY_15MIN = 26  # 6.5-hour session / 15-minute bars
TRADING_DAYS_PER_YEAR = 252
PERIODS_PER_YEAR_15MIN = BARS_PER_TRADING_DAY_15MIN * TRADING_DAYS_PER_YEAR


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
                  fred_api_key=None, news_client=None, finnhub_api_key=None,
                  gates_always_pass=False):
    """Runs decide_trade() bar-by-bar for every symbol, in timestamp order
    across symbols so PDT/drawdown state is shared correctly. Assumes each
    DataFrame in df_by_symbol already has 'time', 'open', and 'close'
    columns (from Task 5's CSV format).

    A signal or stop/target trigger is only knowable once a bar's close
    prints, so any resulting order is queued rather than filled immediately
    -- it fills at that same symbol's *next* bar's open, the earliest a
    live system reacting to the same close could actually have gotten
    filled. Filling at the same bar's own close (the previous behavior)
    would let the backtest trade at a price it could not have known was
    coming. A trigger on a symbol's last available bar has no following bar
    to fill on and is simply left unfilled.

    `gates_always_pass` is forwarded straight into every decide_trade() call
    below -- the plan-specified, supported way to bypass the vix/sentiment/
    earnings gates for testing/synthetic-data runs (see
    scripts/task11_integration_run.py), instead of monkeypatching
    graywind_strategy.pipeline's internals.
    """
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
    # symbol -> order decided off a previous bar's close, awaiting a fill at
    # that same symbol's *next* bar's open (see run_backtest's docstring).
    queued_orders = {}
    last_price_by_symbol = {}
    current_day = None
    # The same-day-pending-position PDT reservation (two symbols each
    # opening a position before either closes can otherwise slip past a
    # realized-only day-trade check and both later close same-day,
    # producing a real violation -- see task-11-report.md for the real
    # backtest run that surfaced this) now lives in
    # PDTThrottle.can_open_day_trade's `pending_count` param and
    # decide_trade's `pending_same_day_trades` param, so both the
    # backtester and the live loop (Task 12) share the same fix instead of
    # each needing to reimplement it.

    # Grouped by timestamp (all_rows is already sorted by time) so the
    # equity curve gets exactly one point per real moment in time, not one
    # point per (bar, symbol) row -- with N symbols sharing the same
    # 15-minute timestamps, appending inside the per-row loop below would
    # otherwise put N duplicate/near-duplicate points on the curve for every
    # real timestamp, corrupting both max_drawdown and sharpe_ratio (which
    # assumes one data point per period).
    for current_time, rows_at_time in groupby(all_rows, key=lambda r: r[0]):
        as_of_date = current_time.date() if hasattr(current_time, "date") else current_time
        if as_of_date != current_day:
            current_day = as_of_date
            drawdown_breaker.start_new_day(current_day, equity)

        for _, symbol, row in rows_at_time:
            open_price = row["open"]
            close_price = row["close"]
            last_price_by_symbol[symbol] = close_price

            # Fill whatever this symbol had queued from its previous bar,
            # at *this* bar's open -- one bar later, and at a different
            # price, than the close that produced the order.
            queued = queued_orders.pop(symbol, None)
            if queued is not None:
                if queued["type"] == "sell":
                    position = open_positions[symbol]
                    equity += (open_price - position["entry_price"]) * position["shares"]
                    trades.append({
                        "symbol": symbol, "action": "sell", "price": open_price,
                        "shares": position["shares"], "time": current_time,
                    })
                    # opened_date here is a `date` object (current_day);
                    # live_loop.py's equivalent comparison uses an ISO
                    # string instead since its state round-trips through
                    # JSON -- a future refactor unifying the two
                    # representations must preserve each caller's own idiom.
                    if position["opened_date"] == current_day:
                        pdt_throttle.record_day_trade(current_day)
                    del open_positions[symbol]
                elif queued["type"] == "buy":
                    decision = queued["decision"]
                    # decision.shares was sized off the full running
                    # `equity` at decision time, with no regard for capital
                    # already committed to other symbols' open positions. A
                    # real broker would reject (or partial-fill) an order
                    # that outspends buying power, so clamp to what's
                    # actually left in cash -- equity minus the cost basis
                    # of every still-open position -- at fill time, instead
                    # of letting combined notional across symbols exceed
                    # account equity.
                    committed_capital = sum(
                        p["entry_price"] * p["shares"] for p in open_positions.values()
                    )
                    available_cash = equity - committed_capital
                    shares = min(decision.shares, int(available_cash // open_price)) if open_price > 0 else 0
                    if shares > 0:
                        open_positions[symbol] = {
                            "entry_price": open_price, "shares": shares,
                            "stop": decision.stop_price, "target": decision.target_price,
                            "opened_date": current_day,
                        }
                        trades.append({
                            "symbol": symbol, "action": "buy", "price": open_price,
                            "shares": shares, "time": current_time,
                        })
                    # else: order expires unfilled -- no cash left to fund it.

            # DrawdownBreaker's contract is "realized+unrealized" losses
            # (see risk/drawdown_breaker.py's docstring), so it must see
            # open positions marked to their latest known price, not just
            # the realized-only `equity` -- otherwise a position drifting
            # deep into unrealized loss without ever hitting its own stop
            # can never trip the shared daily breaker for other symbols.
            mark_to_market_equity = equity + sum(
                (last_price_by_symbol.get(sym, pos["entry_price"]) - pos["entry_price"]) * pos["shares"]
                for sym, pos in open_positions.items()
            )
            drawdown_breaker.update_equity(mark_to_market_equity)

            position = open_positions.get(symbol)
            if position is not None:
                if close_price <= position["stop"] or close_price >= position["target"]:
                    queued_orders[symbol] = {"type": "sell"}
            elif symbol not in queued_orders:
                pending_today = sum(
                    1 for p in open_positions.values() if p["opened_date"] == current_day
                ) + sum(
                    1 for q in queued_orders.values()
                    if q["type"] == "buy" and q["decided_date"] == current_day
                )
                # NOTE (known follow-up, not implemented here): each bar that
                # reaches decide_trade() triggers a fresh vix/sentiment/
                # earnings gate fetch, with no caching across bars for the
                # same (symbol, date). That's fine against synthetic data or
                # with gates_always_pass=True, but a real multi-week backtest
                # run against the real FRED/news/Finnhub APIs (once
                # credentials exist) will need per-(symbol, date) caching of
                # gate results before it's practical against Finnhub's
                # free-tier rate limit (60 req/min) -- not validated here
                # since real credentials/rate-limit behavior aren't available
                # in this environment.
                decision = decide_trade(
                    symbol=symbol, signal=row["signal"], as_of_date=current_day,
                    current_price=close_price, account_equity=equity,
                    pdt_throttle=pdt_throttle, position_sizer=position_sizer,
                    drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
                    fred_api_key=fred_api_key, news_client=news_client,
                    finnhub_api_key=finnhub_api_key,
                    pending_same_day_trades=pending_today,
                    gates_always_pass=gates_always_pass,
                )
                if decision.action == "buy":
                    queued_orders[symbol] = {
                        "type": "buy", "decision": decision, "decided_date": current_day,
                    }

        equity_curve.append(equity)

    pdt_compliant = _check_pdt_compliance(trades) if trades else True

    return BacktestResult(
        equity_curve=equity_curve, trades=trades,
        sharpe=sharpe_ratio(equity_curve, periods_per_year=PERIODS_PER_YEAR_15MIN) if equity_curve else 0.0,
        max_drawdown=max_drawdown(equity_curve) if equity_curve else 0.0,
        win_rate=win_rate(trades),
        pdt_compliant=pdt_compliant,
    )


def _check_pdt_compliance(trades):
    day_trade_dates = []
    open_date_by_symbol = {}
    for trade in trades:  # already chronological: rows were processed in sorted time order
        trade_date = trade["time"].date() if hasattr(trade["time"], "date") else trade["time"]
        symbol = trade["symbol"]
        if trade["action"] == "buy":
            open_date_by_symbol[symbol] = trade_date
        elif trade["action"] == "sell":
            opened = open_date_by_symbol.pop(symbol, None)
            if opened == trade_date:
                day_trade_dates.append(trade_date)

    throttle = PDTThrottle()
    for trade_date in sorted(day_trade_dates):
        if not throttle.can_open_day_trade(trade_date):
            return False
        throttle.record_day_trade(trade_date)
    return True
