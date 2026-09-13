import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.macro_debate import (
    MacroNewsUnavailable,
    STALENESS_CEILING_HOURS,
    fetch_bullion_headlines,
)


def _fake_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    def _raise():
        if status >= 400:
            raise Exception(f"HTTP {status}")
    resp.raise_for_status.side_effect = _raise
    return resp


def test_fetch_bullion_headlines_returns_headlines_list_on_fresh_feed():
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "generated_at": fresh,
        "headlines": [{"headline": "Fed signals pause", "category": "federal"}],
    }
    session = MagicMock()
    session.get.return_value = _fake_response(payload)

    result = fetch_bullion_headlines(session=session)

    assert result == [{"headline": "Fed signals pause", "category": "federal"}]


def test_fetch_bullion_headlines_raises_on_http_error():
    session = MagicMock()
    session.get.return_value = _fake_response({}, status=500)

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


def test_fetch_bullion_headlines_raises_on_malformed_json():
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.side_effect = lambda: None
    resp.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
    session.get.return_value = resp

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


def test_fetch_bullion_headlines_raises_on_missing_keys():
    session = MagicMock()
    session.get.return_value = _fake_response({"unexpected": "shape"})

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


def test_fetch_bullion_headlines_raises_when_stale_past_ceiling():
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(hours=STALENESS_CEILING_HOURS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"generated_at": stale, "headlines": [{"headline": "old news"}]}
    session = MagicMock()
    session.get.return_value = _fake_response(payload)

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)
