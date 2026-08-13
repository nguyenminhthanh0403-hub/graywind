from datetime import date

import pytest

from graywind_strategy.risk.drawdown_breaker import DrawdownBreaker


def test_allows_trading_before_any_loss():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    assert breaker.can_open_new_trade() is True


def test_trips_at_exactly_the_configured_loss_threshold():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    breaker.update_equity(9800)  # exactly -2%
    assert breaker.can_open_new_trade() is False


def test_does_not_trip_under_threshold():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    breaker.update_equity(9801)  # -1.99%
    assert breaker.can_open_new_trade() is True


def test_new_day_resets_the_breaker():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    breaker.start_new_day(date(2024, 1, 8), starting_equity=10000)
    breaker.update_equity(9800)
    assert breaker.can_open_new_trade() is False
    breaker.start_new_day(date(2024, 1, 9), starting_equity=9800)
    assert breaker.can_open_new_trade() is True


def test_init_raises_on_invalid_fraction():
    with pytest.raises(ValueError):
        DrawdownBreaker(max_daily_loss_fraction=0)


def test_start_new_day_raises_on_non_positive_starting_equity():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    with pytest.raises(ValueError):
        breaker.start_new_day(date(2024, 1, 8), starting_equity=0)
    with pytest.raises(ValueError):
        breaker.start_new_day(date(2024, 1, 8), starting_equity=-100)


def test_update_equity_raises_if_called_before_start_new_day():
    breaker = DrawdownBreaker(max_daily_loss_fraction=0.02)
    with pytest.raises(RuntimeError):
        breaker.update_equity(9800)
