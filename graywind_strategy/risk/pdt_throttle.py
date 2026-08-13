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
        # WINDOW_BUSINESS_DAYS is inclusive of as_of itself, so the cutoff
        # is WINDOW_BUSINESS_DAYS - 1 business days back (today + 4 prior
        # business days = 5 business days total).
        cutoff = self._business_days_ago(as_of, self.WINDOW_BUSINESS_DAYS - 1)
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
