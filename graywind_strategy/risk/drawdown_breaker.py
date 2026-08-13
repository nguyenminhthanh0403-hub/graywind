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
