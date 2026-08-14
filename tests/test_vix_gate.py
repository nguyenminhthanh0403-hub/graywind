from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

from graywind_strategy.gates.vix_gate import VixDataUnavailable, fetch_latest_vix, vix_gate


def test_vix_gate_allows_when_below_threshold():
    assert vix_gate(vix_value=18.0, threshold=25.0) is True


def test_vix_gate_blocks_when_at_or_above_threshold():
    assert vix_gate(vix_value=25.0, threshold=25.0) is False
    assert vix_gate(vix_value=30.0, threshold=25.0) is False


def test_fetch_latest_vix_parses_the_most_recent_observation():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "observations": [{"date": "2026-08-12", "value": "17.65"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response

    value = fetch_latest_vix("fake-key", session=fake_session, today=date(2026, 8, 12))

    assert value == 17.65


def test_fetch_latest_vix_raises_on_http_error():
    fake_session = MagicMock()
    fake_session.get.side_effect = Exception("network error")
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session)


def test_fetch_latest_vix_raises_on_missing_value_marker():
    # FRED returns "." for a series with no observation on a given day
    # (e.g. a market holiday) — must not be parsed as a float silently.
    fake_response = MagicMock()
    fake_response.json.return_value = {"observations": [{"date": "2026-08-12", "value": "."}]}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session, today=date(2026, 8, 12))


def test_fetch_latest_vix_raises_when_observation_is_stale():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "observations": [{"date": "2026-07-01", "value": "17.65"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session, today=date(2026, 8, 1))


def test_fetch_latest_vix_accepts_observation_within_staleness_window():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "observations": [{"date": "2026-07-30", "value": "17.65"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    value = fetch_latest_vix("fake-key", session=fake_session, today=date(2026, 8, 1))
    assert value == 17.65


def test_fetch_latest_vix_raises_on_empty_observations_list():
    fake_response = MagicMock()
    fake_response.json.return_value = {"observations": []}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session)


def test_fetch_latest_vix_raises_on_missing_observations_key():
    fake_response = MagicMock()
    fake_response.json.return_value = {}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session)


def test_fetch_latest_vix_raises_on_non_numeric_value():
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "observations": [{"date": "2026-08-12", "value": "not-a-number"}]
    }
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session, today=date(2026, 8, 12))


def test_fetch_latest_vix_raises_on_http_error_status():
    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    with pytest.raises(VixDataUnavailable):
        fetch_latest_vix("fake-key", session=fake_session)


def test_fetch_latest_vix_constrains_query_to_one_day_before_the_given_reference_date():
    # Lets the backtester (Task 11) evaluate historical bars by asking FRED
    # for the observation as of a historical date, rather than always
    # fetching whatever is most recent as of the real "now".
    #
    # Final-review Fix 2: observation_end must be `today - 1 day`, not
    # `today` itself -- `today` is a bar's as-of date (which for an
    # intraday backtest bar can be the SAME calendar day as "right now"),
    # and querying FRED for observation_end=today would return today's own
    # 4:15pm close, a value that same-day intraday bar cannot legitimately
    # see yet. This is real lookahead bias and contradicts the plan's own
    # Global Constraint of gating on *yesterday's* FRED VIXCLS close.
    fake_response = MagicMock()
    fake_response.json.return_value = {"observations": [{"date": "2024-01-07", "value": "15.0"}]}
    fake_response.raise_for_status.return_value = None
    fake_session = MagicMock()
    fake_session.get.return_value = fake_response
    fetch_latest_vix("fake-key", session=fake_session, today=date(2024, 1, 8))
    call_kwargs = fake_session.get.call_args.kwargs
    assert call_kwargs["params"]["observation_end"] == "2024-01-07"
