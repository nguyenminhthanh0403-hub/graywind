import csv
import json
import os
from unittest.mock import MagicMock

import pytest

from graywind_strategy.dashboard_export import log_news_debate
from graywind_strategy.gates.news_debate import (
    Verdict,
    bear_argument,
    bull_argument,
    judge_verdict,
)


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


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


def test_bull_argument_returns_argument_text_from_tool_response():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "Strong earnings beat signals upside."}
    )

    result = bull_argument(fake_client, ["Company beats earnings"])

    assert result == "Strong earnings beat signals upside."


def test_bull_argument_forces_the_bull_tool_and_includes_headlines_in_the_prompt():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "..."}
    )

    bull_argument(fake_client, ["Company beats earnings expectations"])

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {
        "type": "function", "function": {"name": "submit_bull_argument"},
    }
    assert call_kwargs["tools"][0]["function"]["name"] == "submit_bull_argument"
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "Company beats earnings expectations" in prompt_text


def test_bull_argument_disables_thinking_mode():
    # deepseek-v4-flash defaults to thinking mode on, and DeepSeek's API
    # rejects a forced tool_choice (400) while thinking mode is on -- this
    # call would fail against the real API without this flag. See
    # https://github.com/deepseek-ai/DeepSeek-V3/issues/1376.
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bull_argument", {"argument": "..."}
    )

    bull_argument(fake_client, ["Some headline"])

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_bull_argument_raises_on_missing_argument_field():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bull_argument", {}
    )
    with pytest.raises(KeyError):
        bull_argument(fake_client, ["Some headline"])


def test_bull_argument_raises_on_malformed_json_in_tool_call_arguments():
    fake_client = MagicMock()
    fake_tool_call = MagicMock()
    fake_tool_call.function.name = "submit_bull_argument"
    fake_tool_call.function.arguments = "not valid json"
    fake_message = MagicMock()
    fake_message.tool_calls = [fake_tool_call]
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create.return_value = fake_response
    with pytest.raises(json.JSONDecodeError):
        bull_argument(fake_client, ["Some headline"])


def test_bull_argument_raises_when_no_matching_tool_use_block_returned():
    fake_client = MagicMock()
    fake_message = MagicMock()
    fake_message.tool_calls = []
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create.return_value = fake_response
    with pytest.raises(ValueError):
        bull_argument(fake_client, ["Some headline"])


def test_bull_argument_raises_when_tool_calls_is_none():
    # The real OpenAI/DeepSeek response shape has message.tool_calls as
    # None (not []) when the model returns no tool call at all.
    fake_client = MagicMock()
    fake_message = MagicMock()
    fake_message.tool_calls = None
    fake_choice = MagicMock()
    fake_choice.message = fake_message
    fake_response = MagicMock()
    fake_response.choices = [fake_choice]
    fake_client.chat.completions.create.return_value = fake_response
    with pytest.raises(ValueError):
        bull_argument(fake_client, ["Some headline"])


def test_bear_argument_returns_argument_text_from_tool_response():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bear_argument", {"argument": "Fraud investigation signals downside."}
    )

    result = bear_argument(fake_client, ["Company faces fraud investigation"])

    assert result == "Fraud investigation signals downside."


def test_bear_argument_forces_the_bear_tool():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bear_argument", {"argument": "..."}
    )

    bear_argument(fake_client, ["Some headline"])

    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["tool_choice"] == {
        "type": "function", "function": {"name": "submit_bear_argument"},
    }


def test_judge_verdict_parses_score_and_reasoning():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.6, "reasoning": "Bull case outweighs bear case here."}
    )

    verdict = judge_verdict(
        fake_client, ["Company beats earnings"], "bull case text", "bear case text",
    )

    assert verdict == Verdict(score=0.6, reasoning="Bull case outweighs bear case here.")


def test_judge_verdict_includes_both_arguments_in_the_prompt():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.0, "reasoning": "..."}
    )

    judge_verdict(fake_client, ["headline"], "THE BULL CASE", "THE BEAR CASE")

    prompt_text = fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "THE BULL CASE" in prompt_text
    assert "THE BEAR CASE" in prompt_text


def test_judge_verdict_raises_on_missing_score_field():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_verdict", {"reasoning": "no score given"}
    )
    with pytest.raises(KeyError):
        judge_verdict(fake_client, ["headline"], "bull", "bear")


def test_judge_verdict_raises_on_missing_reasoning_field():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_verdict", {"score": 0.5}
    )
    with pytest.raises(KeyError):
        judge_verdict(fake_client, ["headline"], "bull", "bear")


from graywind_strategy.gates.news_debate import evaluate_shadow_debate
from graywind_strategy.gates.sentiment_gate import SentimentDataUnavailable


def _fake_news_client(headlines):
    fake_article_list = []
    for h in headlines:
        article = MagicMock()
        article.headline = h
        fake_article_list.append(article)
    fake_response = MagicMock()
    fake_response.data = {"news": fake_article_list}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response
    return fake_client


def _fake_llm_client_for_debate(score=0.5, reasoning="net positive"):
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = [
        _fake_tool_response("submit_bull_argument", {"argument": "bull case"}),
        _fake_tool_response("submit_bear_argument", {"argument": "bear case"}),
        _fake_tool_response("submit_verdict", {"score": score, "reasoning": reasoning}),
    ]
    return fake_client


def test_evaluate_shadow_debate_returns_vader_and_debate_fields():
    news_client = _fake_news_client(["Analysts praise company for a great, impressive earnings beat"])
    llm_client = _fake_llm_client_for_debate(score=0.7, reasoning="Strong beat outweighs bear case")

    result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache={},
    )

    assert result["vader_score"] > 0.0
    assert result["vader_gate_result"] is True
    assert result["debate_score"] == 0.7
    assert result["debate_reasoning"] == "Strong beat outweighs bear case"


def test_evaluate_shadow_debate_propagates_headline_fetch_failure():
    news_client = MagicMock()
    news_client.get_news.side_effect = Exception("network error")
    llm_client = MagicMock()

    with pytest.raises(SentimentDataUnavailable):
        evaluate_shadow_debate(
            llm_client=llm_client, news_client=news_client, symbol="AAPL",
            as_of_date=None, cache={},
        )
    llm_client.chat.completions.create.assert_not_called()


def test_evaluate_shadow_debate_propagates_malformed_debate_output():
    news_client = _fake_news_client(["Some headline"])
    llm_client = MagicMock()
    llm_client.chat.completions.create.return_value = _fake_tool_response(
        "submit_bull_argument", {}  # missing "argument" -> KeyError
    )

    with pytest.raises(KeyError):
        evaluate_shadow_debate(
            llm_client=llm_client, news_client=news_client, symbol="AAPL",
            as_of_date=None, cache={},
        )


def test_evaluate_shadow_debate_reuses_cached_verdict_for_same_symbol_and_headlines():
    headlines = ["Company beats earnings"]
    news_client = _fake_news_client(headlines)
    llm_client = _fake_llm_client_for_debate(score=0.3, reasoning="first call")
    cache = {}

    first = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache=cache,
    )
    # Second call: same symbol, same headlines (news_client mock still
    # returns the same headline set) -- must hit the cache, not call the
    # LLM again. If it did call again, side_effect (a 3-item list, already
    # exhausted) would raise StopIteration.
    second = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache=cache,
    )

    assert first["debate_score"] == second["debate_score"] == 0.3
    assert llm_client.chat.completions.create.call_count == 3  # not 6 -- second call was a cache hit


def test_evaluate_shadow_debate_does_not_reuse_cache_across_different_symbols():
    headlines = ["Company beats earnings"]
    news_client = _fake_news_client(headlines)
    llm_client = MagicMock()
    llm_client.chat.completions.create.side_effect = [
        _fake_tool_response("submit_bull_argument", {"argument": "bull"}),
        _fake_tool_response("submit_bear_argument", {"argument": "bear"}),
        _fake_tool_response("submit_verdict", {"score": 0.1, "reasoning": "r1"}),
        _fake_tool_response("submit_bull_argument", {"argument": "bull"}),
        _fake_tool_response("submit_bear_argument", {"argument": "bear"}),
        _fake_tool_response("submit_verdict", {"score": 0.2, "reasoning": "r2"}),
    ]
    cache = {}

    aapl_result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache=cache,
    )
    serv_result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="SERV",
        as_of_date=None, cache=cache,
    )

    assert aapl_result["debate_score"] == 0.1
    assert serv_result["debate_score"] == 0.2
    assert llm_client.chat.completions.create.call_count == 6


def test_evaluate_shadow_debate_output_round_trips_through_log_news_debate(tmp_path):
    # Binds evaluate_shadow_debate's real output keys to log_news_debate's
    # expected schema end-to-end -- every other test on either side of this
    # seam uses hand-written dicts, so nothing would otherwise catch a
    # future rename (e.g. debate_score -> score) until it broke in
    # production. See final-review Fix 4.
    news_client = _fake_news_client(["Company beats earnings"])
    llm_client = _fake_llm_client_for_debate(score=0.5, reasoning="net positive")

    result = evaluate_shadow_debate(
        llm_client=llm_client, news_client=news_client, symbol="AAPL",
        as_of_date=None, cache={},
    )
    row = {"timestamp": "2026-08-27T10:00:00-04:00", "symbol": "AAPL", **result}

    dashboard_dir = str(tmp_path)
    log_news_debate(rows=[row], dashboard_dir=dashboard_dir)

    written = _read_csv(os.path.join(dashboard_dir, "news_debate_log.csv"))
    assert len(written) == 1
    assert written[0]["symbol"] == "AAPL"
    assert written[0]["debate_score"] == "0.5"
    assert written[0]["debate_reasoning"] == "net positive"
