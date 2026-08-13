from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.sentiment_gate import (
    SentimentDataUnavailable,
    fetch_recent_headlines,
    sentiment_gate,
    sentiment_score,
)


def test_sentiment_score_of_empty_headlines_is_neutral():
    assert sentiment_score([]) == 0.0


def test_sentiment_score_positive_headlines_scores_above_zero():
    # NOTE: deviates from the task-8 brief's literal example headline ("Company
    # beats earnings expectations by a wide margin"), which VADER scores as
    # perfectly neutral (compound 0.0) -- none of "beats"/"earnings"/
    # "expectations"/"margin" are sentiment-bearing words in VADER's lexicon.
    # Verified directly against the installed vaderSentiment package. Swapped
    # in a headline that VADER's lexicon actually recognizes as positive,
    # preserving the test's intent (positive headline -> score > 0).
    score = sentiment_score(["Analysts praise company for delivering a great, impressive earnings beat"])
    assert score > 0.0


def test_sentiment_score_negative_headlines_scores_below_zero():
    score = sentiment_score(["Company misses on revenue, shares plunge on fraud investigation"])
    assert score < 0.0


def test_sentiment_gate_allows_above_threshold():
    assert sentiment_gate(score=0.0, threshold=-0.2) is True


def test_sentiment_gate_blocks_below_threshold():
    assert sentiment_gate(score=-0.5, threshold=-0.2) is False


def test_fetch_recent_headlines_extracts_headline_field():
    fake_article = MagicMock()
    fake_article.headline = "Some Headline"
    fake_response = MagicMock()
    fake_response.data = {"news": [fake_article]}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response

    headlines = fetch_recent_headlines(fake_client, "AAPL", limit=5)

    assert headlines == ["Some Headline"]
    fake_client.get_news.assert_called_once()


def test_fetch_recent_headlines_raises_on_client_error():
    fake_client = MagicMock()
    fake_client.get_news.side_effect = Exception("network error")
    with pytest.raises(SentimentDataUnavailable):
        fetch_recent_headlines(fake_client, "AAPL")
