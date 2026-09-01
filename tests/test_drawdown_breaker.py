from datetime import date

import pytest

from graywind_strategy.risk.drawdown_breaker import (
    DrawdownBreaker, RollingDrawdownBreaker, ROLLING_DRAWDOWN_LIMITS,
    build_rolling_breakers, widest_history,
)


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


# --- RollingDrawdownBreaker -------------------------------------------------
# Cold-start permissiveness is the safety-critical property here: this breaker
# ships into a live cron whose state dir has no equity history at all, and a
# fail-closed cold start would silently halt trading on the first cycle after
# deploy. The first three tests pin that behavior deliberately.


def test_rolling_allows_trading_with_no_history_at_all():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    assert breaker.can_open_new_trade() is True


def test_rolling_allows_trading_with_a_single_data_point():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 8), 10000)
    assert breaker.can_open_new_trade() is True


def test_rolling_allows_trading_when_history_is_shorter_than_the_window():
    breaker = RollingDrawdownBreaker(window_days=30, max_loss_fraction=0.10)
    breaker.record_equity(date(2024, 1, 8), 10000)
    breaker.record_equity(date(2024, 1, 9), 9950)
    assert breaker.can_open_new_trade() is True


def test_rolling_trips_at_exactly_the_configured_loss_threshold_from_window_peak():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 8), 10000)
    breaker.record_equity(date(2024, 1, 10), 9500)  # exactly -5% off the peak
    assert breaker.can_open_new_trade() is False


def test_rolling_does_not_trip_just_under_threshold():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 8), 10000)
    breaker.record_equity(date(2024, 1, 10), 9501)  # -4.99%
    assert breaker.can_open_new_trade() is True


def test_rolling_measures_from_the_window_peak_not_the_first_point():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 8), 9000)
    breaker.record_equity(date(2024, 1, 9), 10000)  # peak arrives mid-window
    breaker.record_equity(date(2024, 1, 10), 9500)  # -5% from the peak
    assert breaker.can_open_new_trade() is False


def test_rolling_ignores_a_peak_that_has_aged_out_of_the_window():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 1), 10000)  # peak, will age out
    breaker.record_equity(date(2024, 1, 20), 9500)  # 19 days later
    assert breaker.can_open_new_trade() is True


def test_rolling_is_not_latching_and_recovers_when_drawdown_narrows():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 8), 10000)
    breaker.record_equity(date(2024, 1, 9), 9500)
    assert breaker.can_open_new_trade() is False
    breaker.record_equity(date(2024, 1, 10), 9900)  # recovered to -1%
    assert breaker.can_open_new_trade() is True


def test_rolling_recording_the_same_day_twice_replaces_rather_than_duplicates():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 8), 10000)
    breaker.record_equity(date(2024, 1, 9), 9500)
    breaker.record_equity(date(2024, 1, 9), 9900)  # same day, revised upward
    assert breaker.can_open_new_trade() is True
    assert breaker.history_rows() == [(date(2024, 1, 8), 10000.0), (date(2024, 1, 9), 9900.0)]


def test_rolling_load_history_accepts_persisted_rows():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.load_history([(date(2024, 1, 8), 10000.0), (date(2024, 1, 9), 9500.0)])
    assert breaker.can_open_new_trade() is False


def test_rolling_history_rows_are_pruned_to_the_window():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    breaker.record_equity(date(2024, 1, 1), 10000)
    breaker.record_equity(date(2024, 1, 20), 9900)
    assert breaker.history_rows() == [(date(2024, 1, 20), 9900.0)]


def test_rolling_init_raises_on_invalid_arguments():
    with pytest.raises(ValueError):
        RollingDrawdownBreaker(window_days=7, max_loss_fraction=0)
    with pytest.raises(ValueError):
        RollingDrawdownBreaker(window_days=7, max_loss_fraction=1)
    with pytest.raises(ValueError):
        RollingDrawdownBreaker(window_days=0, max_loss_fraction=0.05)


def test_rolling_record_equity_raises_on_non_positive_equity():
    breaker = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    with pytest.raises(ValueError):
        breaker.record_equity(date(2024, 1, 8), 0)
    with pytest.raises(ValueError):
        breaker.record_equity(date(2024, 1, 8), -100)


def test_build_rolling_breakers_matches_the_shared_limits():
    # live_loop.py and backtester.py both build from this, so a symbol cleared
    # by the backtest gate was vetted under the live risk regime.
    breakers = build_rolling_breakers()
    assert [(b.window_days, b.max_loss_fraction) for b in breakers] == list(ROLLING_DRAWDOWN_LIMITS)


def test_widest_history_returns_the_longest_window_breakers_rows():
    breakers = build_rolling_breakers()
    for breaker in breakers:
        breaker.record_equity(date(2024, 1, 1), 10000)
        breaker.record_equity(date(2024, 1, 20), 9900)
    # The 7-day breaker has pruned Jan 1; the 30-day one has not. Persisting the
    # wider one keeps the rows the shorter window would need after a gap.
    assert widest_history(breakers) == [(date(2024, 1, 1), 10000.0), (date(2024, 1, 20), 9900.0)]


def test_widest_history_of_no_breakers_is_empty():
    assert widest_history([]) == []


def test_a_slow_bleed_that_never_trips_the_daily_breaker_trips_the_weekly_one():
    # The reason this class exists: -1.9% a day clears the 2% daily limit every
    # single day, while compounding into a >5% hole inside one week.
    daily = DrawdownBreaker(max_daily_loss_fraction=0.02)
    weekly = RollingDrawdownBreaker(window_days=7, max_loss_fraction=0.05)
    equity = 100000.0
    for day_offset in range(1, 5):
        previous_equity = equity
        equity *= 0.981
        daily.start_new_day(date(2026, 9, day_offset), previous_equity)
        daily.update_equity(equity)
        weekly.record_equity(date(2026, 9, day_offset), equity)
        assert daily.can_open_new_trade() is True  # never trips
    assert weekly.can_open_new_trade() is False
