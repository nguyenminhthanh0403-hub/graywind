from datetime import date

from graywind_strategy.risk.pdt_throttle import PDTThrottle


def test_can_open_day_trade_true_when_no_trades_recorded():
    throttle = PDTThrottle()
    assert throttle.can_open_day_trade(date(2024, 1, 8)) is True


def test_allows_up_to_three_day_trades_then_blocks_fourth():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))   # Mon
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    assert throttle.can_open_day_trade(date(2024, 1, 11)) is False  # Thu


def test_weekend_days_are_not_counted_in_the_five_business_day_window():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))   # Mon
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    # Jan 13-14 is a weekend; if weekends were miscounted as business days,
    # this would incorrectly read as True.
    assert throttle.can_open_day_trade(date(2024, 1, 15)) is False  # Mon


def test_oldest_day_trade_ages_out_of_the_five_business_day_window():
    throttle = PDTThrottle()
    throttle.record_day_trade(date(2024, 1, 8))   # Mon
    throttle.record_day_trade(date(2024, 1, 9))   # Tue
    throttle.record_day_trade(date(2024, 1, 10))  # Wed
    assert throttle.can_open_day_trade(date(2024, 1, 16)) is True  # Tue, Jan 8 aged out
