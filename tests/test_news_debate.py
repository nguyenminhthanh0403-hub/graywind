from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.news_debate import (
    Verdict,
    bear_argument,
    bull_argument,
    judge_verdict,
)


def _fake_tool_response(tool_name, input_dict):
    fake_block = MagicMock()
    fake_block.type = "tool_use"
    fake_block.name = tool_name
    fake_block.input = input_dict
    fake_response = MagicMock()
    fake_response.content = [fake_block]
    return fake_response


def test_bull_argument_returns_argument_text_from_tool_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "Strong earnings beat signals upside."}
    )

    result = bull_argument(fake_client, ["Company beats earnings"])

    assert result == "Strong earnings beat signals upside."


def test_bull_argument_forces_the_bull_tool_and_includes_headlines_in_the_prompt():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "..."}
    )

    bull_argument(fake_client, ["Company beats earnings expectations"])

    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_bull_argument"}
    assert call_kwargs["tools"][0]["name"] == "submit_bull_argument"
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "Company beats earnings expectations" in prompt_text


def test_bull_argument_raises_on_missing_argument_field():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bull_argument", {}
    )
    with pytest.raises(KeyError):
        bull_argument(fake_client, ["Some headline"])


def test_bull_argument_raises_when_no_matching_tool_use_block_returned():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.content = []
    fake_client.messages.create.return_value = fake_response
    with pytest.raises(ValueError):
        bull_argument(fake_client, ["Some headline"])


def test_bear_argument_returns_argument_text_from_tool_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bear_argument", {"argument": "Fraud investigation signals downside."}
    )

    result = bear_argument(fake_client, ["Company faces fraud investigation"])

    assert result == "Fraud investigation signals downside."


def test_bear_argument_forces_the_bear_tool():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_bear_argument", {"argument": "..."}
    )

    bear_argument(fake_client, ["Some headline"])

    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {"type": "tool", "name": "submit_bear_argument"}


def test_judge_verdict_parses_score_and_reasoning():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.6, "reasoning": "Bull case outweighs bear case here."}
    )

    verdict = judge_verdict(
        fake_client, ["Company beats earnings"], "bull case text", "bear case text",
    )

    assert verdict == Verdict(score=0.6, reasoning="Bull case outweighs bear case here.")


def test_judge_verdict_includes_both_arguments_in_the_prompt():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.0, "reasoning": "..."}
    )

    judge_verdict(fake_client, ["headline"], "THE BULL CASE", "THE BEAR CASE")

    prompt_text = fake_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "THE BULL CASE" in prompt_text
    assert "THE BEAR CASE" in prompt_text


def test_judge_verdict_raises_on_missing_score_field():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"reasoning": "no score given"}
    )
    with pytest.raises(KeyError):
        judge_verdict(fake_client, ["headline"], "bull", "bear")


def test_judge_verdict_raises_on_missing_reasoning_field():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.5}
    )
    with pytest.raises(KeyError):
        judge_verdict(fake_client, ["headline"], "bull", "bear")
