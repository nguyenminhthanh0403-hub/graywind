from datetime import date
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.analyst_consensus import (
    AnalystDataUnavailable,
    analyst_consensus_multiplier,
    fetch_analyst_consensus,
    load_cached_multiplier,
    save_cached_multiplier,
)


def test_multiplier_strong_buy_at_current_price_target():
    # recommendation_mean=1.0 (Strong Buy), target_mean == current_price (0% upside)
    result = analyst_consensus_multiplier(
        recommendation_mean=1.0, target_mean=100.0, current_price=100.0
    )
    assert result == 1.075  # (1.15 + 1.00) / 2


def test_multiplier_strong_sell_at_current_price_target():
    result = analyst_consensus_multiplier(
        recommendation_mean=5.0, target_mean=100.0, current_price=100.0
    )
    assert result == 0.925  # (0.85 + 1.00) / 2


def test_multiplier_hold_with_zero_upside_is_exactly_neutral():
    result = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=100.0, current_price=100.0
    )
    assert result == 1.0


def test_multiplier_clamps_upside_beyond_15_percent():
    # target_mean is 30% above current_price -- clamps to the same result as exactly +15%
    result_30pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=130.0, current_price=100.0
    )
    result_15pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=115.0, current_price=100.0
    )
    assert result_30pct == result_15pct == 1.075  # (1.00 + 1.15) / 2


def test_multiplier_clamps_downside_beyond_15_percent():
    result_30pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=70.0, current_price=100.0
    )
    result_15pct = analyst_consensus_multiplier(
        recommendation_mean=3.0, target_mean=85.0, current_price=100.0
    )
    assert result_30pct == result_15pct == 0.925  # (1.00 + 0.85) / 2


def test_multiplier_clamps_recommendation_mean_outside_1_to_5():
    # a recommendation_mean of 7 (outside Yahoo's documented 1-5 scale) clamps to 5 (Strong Sell)
    result_out_of_range = analyst_consensus_multiplier(
        recommendation_mean=7.0, target_mean=100.0, current_price=100.0
    )
    result_at_bound = analyst_consensus_multiplier(
        recommendation_mean=5.0, target_mean=100.0, current_price=100.0
    )
    assert result_out_of_range == result_at_bound == 0.925


def test_multiplier_clamps_recommendation_mean_below_1():
    # a recommendation_mean below 1.0 (outside Yahoo's documented 1-5 scale) clamps to 1 (Strong Buy)
    result_out_of_range = analyst_consensus_multiplier(
        recommendation_mean=0.5, target_mean=100.0, current_price=100.0
    )
    result_at_bound = analyst_consensus_multiplier(
        recommendation_mean=1.0, target_mean=100.0, current_price=100.0
    )
    assert result_out_of_range == result_at_bound == 1.075


def test_fetch_analyst_consensus_returns_recommendation_and_target():
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": 2.1, "targetMeanPrice": 210.5}
    fake_ticker_factory = MagicMock(return_value=fake_ticker)

    result = fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)

    assert result == (2.1, 210.5)
    fake_ticker_factory.assert_called_once_with("AAPL")


def test_fetch_analyst_consensus_raises_on_ticker_exception():
    fake_ticker_factory = MagicMock(side_effect=Exception("network error"))
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_on_missing_recommendation_mean():
    fake_ticker = MagicMock()
    fake_ticker.info = {"targetMeanPrice": 210.5}  # recommendationMean absent
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_on_missing_target_mean_price():
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": 2.1}  # targetMeanPrice absent
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_analyst_data_unavailable_on_non_numeric_field():
    # A real possibility from an unofficial scraper library: Yahoo returns a
    # non-numeric placeholder like "N/A" instead of omitting the field. The
    # float() conversion must happen inside the try so this raises
    # AnalystDataUnavailable, not an unhandled ValueError that would
    # propagate out of decide_trade.
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": "N/A", "targetMeanPrice": 210.5}
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_analyst_data_unavailable_on_nan_recommendation_mean():
    # A NaN would pass the `is None` check and pass float() silently, then
    # get clamped into an arbitrary extreme bound -- a confidently WRONG
    # signal. math.isfinite() must catch this and fail open instead.
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": float("nan"), "targetMeanPrice": 210.5}
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_fetch_analyst_consensus_raises_analyst_data_unavailable_on_nan_target_mean():
    fake_ticker = MagicMock()
    fake_ticker.info = {"recommendationMean": 2.1, "targetMeanPrice": float("nan")}
    fake_ticker_factory = MagicMock(return_value=fake_ticker)
    with pytest.raises(AnalystDataUnavailable):
        fetch_analyst_consensus("AAPL", ticker_factory=fake_ticker_factory)


def test_load_cached_multiplier_returns_none_when_file_does_not_exist(tmp_path):
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_save_then_load_round_trips_the_multiplier(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result == 1.075


def test_load_cached_multiplier_misses_on_a_different_date(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    result = load_cached_multiplier("AAPL", date(2026, 8, 19), state_dir=str(tmp_path))
    assert result is None


def test_load_cached_multiplier_misses_on_a_different_symbol(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    result = load_cached_multiplier("MSFT", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_save_appends_rather_than_overwrites_other_symbols(tmp_path):
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    save_cached_multiplier(
        "MSFT", date(2026, 8, 18),
        recommendation_mean=1.8, target_mean=420.0, multiplier=1.1,
        state_dir=str(tmp_path),
    )
    assert load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path)) == 1.075
    assert load_cached_multiplier("MSFT", date(2026, 8, 18), state_dir=str(tmp_path)) == 1.1


def test_load_cached_multiplier_treats_malformed_row_as_a_miss(tmp_path):
    os_makedirs_path = tmp_path / "analyst_consensus.csv"
    os_makedirs_path.write_text(
        "symbol,date,recommendation_mean,target_mean,multiplier\n"
        "AAPL,2026-08-18,2.1,210.5,not-a-number\n"
    )
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_load_cached_multiplier_treats_corrupt_file_as_a_miss(tmp_path):
    (tmp_path / "analyst_consensus.csv").write_bytes(b"\xff\xfe\x00\x01not,csv,at,all")
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result is None


def test_load_cached_multiplier_skips_malformed_row_and_finds_later_valid_row(tmp_path):
    # Manually create a malformed row for (AAPL, 2026-08-18)
    csv_path = tmp_path / "analyst_consensus.csv"
    csv_path.write_text(
        "symbol,date,recommendation_mean,target_mean,multiplier\n"
        "AAPL,2026-08-18,2.1,210.5,not-a-number\n"
    )
    # Then append a valid row for the same key
    save_cached_multiplier(
        "AAPL", date(2026, 8, 18),
        recommendation_mean=2.1, target_mean=210.5, multiplier=1.075,
        state_dir=str(tmp_path),
    )
    # The load should skip the malformed row and find the valid one
    result = load_cached_multiplier("AAPL", date(2026, 8, 18), state_dir=str(tmp_path))
    assert result == 1.075
