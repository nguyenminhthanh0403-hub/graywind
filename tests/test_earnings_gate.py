from datetime import date
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.earnings_gate import (
    EarningsDataUnavailable,
    earnings_gate,
    fetch_next_earnings_date,
)


def test_earnings_gate_allows_when_no_earnings_scheduled():
    assert earnings_gate(next_earnings_date=None, as_of_date=date(2024, 1, 8)) is True


def test_earnings_gate_blocks_within_blackout_window():
    assert earnings_gate(
        next_earnings_date=date(2024, 1, 10), as_of_date=date(2024, 1, 8), blackout_days=3
    ) is False


def test_earnings_gate_allows_outside_blackout_window():
    assert earnings_gate(
        next_earnings_date=date(2024, 1, 20), as_of_date=date(2024, 1, 8), blackout_days=3
    ) is True


def test_earnings_gate_allows_when_earnings_date_already_passed():
    assert earnings_gate(
        next_earnings_date=date(2024, 1, 1), as_of_date=date(2024, 1, 8), blackout_days=3
    ) is True


def test_fetch_next_earnings_date_returns_earliest_date_in_window():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "earningsCalendar": [{"date": "2024-01-25"}, {"date": "2024-01-18"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = fetch_next_earnings_date("AAPL", "fake-key", date(2024, 1, 8), session=fake_session)

    assert result == date(2024, 1, 18)


def test_fetch_next_earnings_date_returns_none_when_calendar_is_empty():
    fake_response = MagicMock()
    fake_response.json.return_value = {"earningsCalendar": []}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    result = fetch_next_earnings_date("AAPL", "fake-key", date(2024, 1, 8), session=fake_session)

    assert result is None


def test_fetch_next_earnings_date_raises_on_http_error():
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network error")
    with pytest.raises(EarningsDataUnavailable):
        fetch_next_earnings_date("AAPL", "fake-key", date(2024, 1, 8), session=fake_session)
