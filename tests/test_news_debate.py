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
    fake_client.messages.create.side_effect = [
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
    llm_client.messages.create.assert_not_called()


def test_evaluate_shadow_debate_propagates_malformed_debate_output():
    news_client = _fake_news_client(["Some headline"])
    llm_client = MagicMock()
    llm_client.messages.create.return_value = _fake_tool_response(
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
    assert llm_client.messages.create.call_count == 3  # not 6 -- second call was a cache hit


def test_evaluate_shadow_debate_does_not_reuse_cache_across_different_symbols():
    headlines = ["Company beats earnings"]
    news_client = _fake_news_client(headlines)
    llm_client = MagicMock()
    llm_client.messages.create.side_effect = [
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
    assert llm_client.messages.create.call_count == 6
