from datetime import date

from graywind_strategy.risk.pdt_throttle import PDTThrottle


def test_can_open_day_trade_true_when_no_trades_recorded():
    throttle = PDTThrottle()
    assert throttle.can_open_day_trade(date(2024, 1, 8)) is True


def test_allows_up_to_three_day_trades_then_blocks_fourth():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    throttle.record_day_trade(date(2024, 1, 11))  # Thu
    assert throttle.can_open_day_trade(date(2024, 1, 12)) is False  # Fri


def test_weekend_days_are_not_counted_in_the_five_business_day_window():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    throttle.record_day_trade(date(2024, 1, 11))  # Thu
    # Jan 13-14 is a weekend. The Jan 9 trade is exactly 5 business days
    # back from Jan 15 (Jan 9,10,11,12,15) so it must still count here —
    # if weekends were wrongly treated as business days (e.g. naive
    # `as_of - timedelta(days=4)`), the cutoff would land on Jan 11
    # instead of Jan 9, wrongly pruning Jan 9 and Jan 10 and returning
    # True instead of False.
    assert throttle.can_open_day_trade(date(2024, 1, 15)) is False  # Mon


def test_oldest_day_trade_ages_out_of_the_five_business_day_window():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    throttle.record_day_trade(date(2024, 1, 11))  # Thu
    assert throttle.can_open_day_trade(date(2024, 1, 16)) is True  # Tue, Jan 9 aged out (5 business days: 9,10,11,12,15 — Jan 16 is the 6th)


def test_can_open_day_trade_accounts_for_pending_count():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))
    throttle.record_day_trade(date(2024, 1, 9))
    # 2 realized + 1 pending = 3, at the cap -> blocked
    assert throttle.can_open_day_trade(date(2024, 1, 9), pending_count=1) is False
    # 2 realized + 0 pending = 2, under the cap -> allowed
    assert throttle.can_open_day_trade(date(2024, 1, 9), pending_count=0) is True
