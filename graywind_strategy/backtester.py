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
    # The same-day-pending-position PDT reservation (two symbols each
    # opening a position before either closes can otherwise slip past a
    # realized-only day-trade check and both later close same-day,
    # producing a real violation -- see task-11-report.md for the real
    # backtest run that surfaced this) now lives in
    # PDTThrottle.can_open_day_trade's `pending_count` param and
    # decide_trade's `pending_same_day_trades` param, so both the
    # backtester and the live loop (Task 12) share the same fix instead of
    # each needing to reimplement it.

    for time, symbol, row in all_rows:
        as_of_date = time.date() if hasattr(time, "date") else time
        if as_of_date != current_day:
            current_day = as_of_date
            drawdown_breaker.start_new_day(current_day, equity)

        price = row["close"]

        position = open_positions.get(symbol)
        if position is not None and (price <= position["stop"] or price >= position["target"]):
            equity += (price - position["entry_price"]) * position["shares"]
            trades.append({
                "symbol": symbol, "action": "sell", "price": price,
                "shares": position["shares"], "time": time,
            })
            if position["opened_date"] == current_day:
                pdt_throttle.record_day_trade(current_day)
            del open_positions[symbol]

        drawdown_breaker.update_equity(equity)

        if symbol not in open_positions:
            pending_today = sum(
                1 for p in open_positions.values() if p["opened_date"] == current_day
            )
            decision = decide_trade(
                symbol=symbol, signal=row["signal"], as_of_date=current_day,
                current_price=price, account_equity=equity,
                pdt_throttle=pdt_throttle, position_sizer=position_sizer,
                drawdown_breaker_ok=drawdown_breaker.can_open_new_trade(),
                fred_api_key=fred_api_key, news_client=news_client,
                finnhub_api_key=finnhub_api_key,
                pending_same_day_trades=pending_today,
            )
            if decision.action == "buy":
                open_positions[symbol] = {
                    "entry_price": price, "shares": decision.shares,
                    "stop": decision.stop_price, "target": decision.target_price,
                    "opened_date": current_day,
                }
                trades.append({
                    "symbol": symbol, "action": "buy", "price": price,
                    "shares": decision.shares, "time": time,
                })

        equity_curve.append(equity)

    pdt_compliant = _check_pdt_compliance(trades) if trades else True

    return BacktestResult(
        equity_curve=equity_curve, trades=trades,
        sharpe=sharpe_ratio(equity_curve) if equity_curve else 0.0,
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
