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


def test_fetch_bullion_headlines_raises_on_empty_headlines_list():
    now = datetime.now(timezone.utc)
    fresh = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"generated_at": fresh, "headlines": []}
    session = MagicMock()
    session.get.return_value = _fake_response(payload)

    with pytest.raises(MacroNewsUnavailable):
        fetch_bullion_headlines(session=session)


from graywind_strategy.gates.macro_debate import MacroEvent, evaluate_macro_events


def _fake_tool_response(tool_name, input_dict):
    fake_tool_call = MagicMock()
    fake_tool_call.function.name = tool_name
    fake_tool_call.function.arguments = json.dumps(input_dict)
    fake_message = MagicMock()
    fake_message.tool_calls = [fake_tool_call]
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    return fake_response


def test_evaluate_macro_events_parses_response_into_macro_events():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events",
        {"events": [
            {"event": "Fed cuts rates in December", "probability": 0.6,
             "implication": "Bullish for rate-sensitive equities"},
        ]},
    )

    result = evaluate_macro_events(fake_client, [{"headline": "Fed signals pause"}])

    assert result == [MacroEvent(
        event="Fed cuts rates in December", probability=0.6,
        implication="Bullish for rate-sensitive equities",
    )]


def test_evaluate_macro_events_forces_tool_and_disables_thinking():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events", {"events": [
            {"event": "e", "probability": 0.5, "implication": "i"},
        ]},
    )

    evaluate_macro_events(fake_client, [{"headline": "Fed signals pause"}])

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {
        "type": "function", "function": {"name": "submit_macro_events"},
    }
    assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "Fed signals pause" in prompt_text


def test_evaluate_macro_events_raises_on_malformed_response():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events", {"events": [{"event": "e"}]},
    )

    with pytest.raises(KeyError):
        evaluate_macro_events(fake_client, [{"headline": "x"}])


def test_evaluate_macro_events_raises_on_out_of_range_probability():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_macro_events",
        {"events": [
            {"event": "Fed cuts rates in December", "probability": 60.0,
             "implication": "Bullish for rate-sensitive equities"},
        ]},
    )

    with pytest.raises(ValueError):
        evaluate_macro_events(fake_client, [{"headline": "Fed signals pause"}])


from unittest.mock import patch

from graywind_strategy.gates.macro_debate import evaluate_macro_debate


def test_evaluate_macro_debate_returns_dicts_without_timestamp():
    with patch(
        "graywind_strategy.gates.macro_debate.fetch_bullion_headlines",
        return_value=[{"headline": "Fed signals pause"}],
    ), patch(
        "graywind_strategy.gates.macro_debate.evaluate_macro_events",
        return_value=[MacroEvent(event="e", probability=0.5, implication="i")],
    ):
        result = evaluate_macro_debate(llm_client=object())

    assert result == [{"event": "e", "probability": 0.5, "implication": "i"}]


def test_evaluate_macro_debate_propagates_fetch_failure():
    with patch(
        "graywind_strategy.gates.macro_debate.fetch_bullion_headlines",
        side_effect=MacroNewsUnavailable("stale"),
    ):
        with pytest.raises(MacroNewsUnavailable):
            evaluate_macro_debate(llm_client=object())
