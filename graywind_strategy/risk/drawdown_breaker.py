"""Drawdown circuit breakers.

DrawdownBreaker is the intraday one: it halts new trades for the rest of the
day once realized+unrealized losses reach a configured fraction of
starting-of-day account equity, and resets on start_new_day.

RollingDrawdownBreaker sits ABOVE it and spans days, catching the failure the
daily breaker structurally cannot see: a slow bleed of -1.9% per day, every
day, which never trips a 2% daily limit but compounds into a serious hole
across a week or a month.

Two deliberate behavioral differences from the daily breaker, both of which
are safety-relevant and easy to "fix" into something worse:

1. It is NON-LATCHING. The daily breaker latches until the next day because
   its baseline (start-of-day equity) is fixed. A rolling window's baseline
   moves, so this one is recomputed from current history on every call and
   will re-permit trading when the drawdown narrows or the peak ages out.
2. It is PERMISSIVE ON THIN DATA. With no history, one point, or a window
   whose peak equals the current value, it returns True. This is required,
   not incidental: this class ships into a live cron whose state directory
   has no equity history at all on the first cycle after deploy, and
   decide_trade treats a falsy drawdown_breaker_ok as a block. A fail-closed
   cold start would silently halt all live trading until 30 days of history
   accrued. The permissiveness is bounded -- the daily breaker still covers
   the intraday case while this one's history fills in.
"""
from datetime import timedelta

# PROVISIONAL, pending owner sign-off -- see
# docs/superpowers/graywind-real-capital-done-criteria.md. Laddered off the 2%
# daily limit rather than picked independently: ~2.5 full daily-limit days in a
# week, ~5 in a month. Defined here, and consumed via build_rolling_breakers()
# by both live_loop.py and backtester.py, so live trading and the symbol-
# validation backtest cannot drift into different risk regimes.
ROLLING_DRAWDOWN_LIMITS = ((7, 0.05), (30, 0.10))  # (window_days, max_loss_fraction)


class DrawdownBreaker:
    def __init__(self, max_daily_loss_fraction=0.02):
        if not 0 < max_daily_loss_fraction < 1:
            raise ValueError("max_daily_loss_fraction must be between 0 and 1")
        self.max_daily_loss_fraction = max_daily_loss_fraction
        self._current_day = None
        self._start_of_day_equity = 0.0
        self._tripped = False

    def start_new_day(self, day, starting_equity):
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self._current_day = day
        self._start_of_day_equity = starting_equity
        self._tripped = False

    def update_equity(self, current_equity):
        if self._current_day is None:
            raise RuntimeError("update_equity called before start_new_day")
        loss_fraction = (self._start_of_day_equity - current_equity) / self._start_of_day_equity
        if loss_fraction >= self.max_daily_loss_fraction:
            self._tripped = True

    def can_open_new_trade(self):
        return not self._tripped


class RollingDrawdownBreaker:
    def __init__(self, window_days, max_loss_fraction):
        if not 0 < max_loss_fraction < 1:
            raise ValueError("max_loss_fraction must be between 0 and 1")
        if window_days < 1:
            raise ValueError("window_days must be at least 1")
        self.window_days = window_days
        self.max_loss_fraction = max_loss_fraction
        self._equity_by_day = {}

    def load_history(self, rows):
        """Seeds history from persisted (day, equity) rows. Replaces whatever
        is held, so a caller can load once per cycle without accumulating.
        """
        self._equity_by_day = {day: float(equity) for day, equity in rows}
        self._prune()

    def record_equity(self, day, equity):
        if equity <= 0:
            raise ValueError("equity must be positive")
        # Upsert rather than append: the live loop runs many cycles per day, and
        # one row per calendar day keeps the persisted file bounded by the window
        # instead of growing with cycle count.
        self._equity_by_day[day] = float(equity)
        self._prune()

    def history_rows(self):
        return sorted(self._equity_by_day.items())

    def can_open_new_trade(self):
        rows = self.history_rows()
        if len(rows) < 2:
            return True  # cold start -- see module docstring
        peak = max(equity for _, equity in rows)
        current = rows[-1][1]
        if peak <= 0:
            return True
        return (peak - current) / peak < self.max_loss_fraction

    def _prune(self):
        if not self._equity_by_day:
            return
        cutoff = max(self._equity_by_day) - timedelta(days=self.window_days)
        self._equity_by_day = {
            day: equity for day, equity in self._equity_by_day.items() if day > cutoff
        }


def build_rolling_breakers(limits=ROLLING_DRAWDOWN_LIMITS):
    return [
        RollingDrawdownBreaker(window_days=window, max_loss_fraction=fraction)
        for window, fraction in limits
    ]


def widest_history(breakers):
    """History rows of the longest-window breaker -- a superset of every
    shorter window's, so persisting it preserves what all of them need.
    """
    if not breakers:
        return []
    return max(breakers, key=lambda b: b.window_days).history_rows()
