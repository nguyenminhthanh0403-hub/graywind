from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.analyst_consensus import (
    AnalystDataUnavailable,
    analyst_consensus_multiplier,
    fetch_analyst_consensus,
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
