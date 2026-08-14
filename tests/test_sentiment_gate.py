from datetime import date, datetime, time, timedelta
from unittest.mock import MagicMock

import pytest

from graywind_strategy.gates.sentiment_gate import (
    SENTIMENT_LOOKBACK_DAYS,
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


def test_fetch_recent_headlines_constrains_query_to_the_given_reference_date():
    # NewsRequest.model_fields (alpaca-py 0.44.0) confirms the fields are
    # literally `start`/`end`, both typed datetime.datetime | None -- verified
    # via the same static-inspection technique used for the `symbols` field
    # above. `start` must be sent explicitly: per NewsRequest's docstring,
    # an omitted `start` defaults server-side to the beginning of the
    # *current* day, not `end`'s day, which would invert the window for any
    # historical as_of. Lets the backtester (Task 11) evaluate historical
    # bars without the sentiment gate leaking future news into the score.
    fake_response = MagicMock()
    fake_response.data = {"news": []}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response

    fetch_recent_headlines(fake_client, "AAPL", as_of=date(2024, 1, 8))

    fake_client.get_news.assert_called_once()
    request = fake_client.get_news.call_args.args[0]
    assert request.start == datetime.combine(
        date(2024, 1, 8) - timedelta(days=SENTIMENT_LOOKBACK_DAYS), time.min
    )
    assert request.end == datetime.combine(date(2024, 1, 8), time.max)


def test_fetch_recent_headlines_serializes_both_start_and_end_when_as_of_given():
    # Checking the Python attributes (above) isn't sufficient proof -- this
    # mirrors the exact technique that caught the original gap in review:
    # serialize the request the way the SDK would before sending it over the
    # wire, and confirm `start` is actually present, not silently dropped.
    fake_response = MagicMock()
    fake_response.data = {"news": []}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response

    fetch_recent_headlines(fake_client, "AAPL", as_of=date(2024, 1, 8))

    request = fake_client.get_news.call_args.args[0]
    fields = request.to_request_fields()
    assert "start" in fields
    assert "end" in fields


def test_fetch_recent_headlines_omits_start_and_end_when_as_of_not_given():
    fake_response = MagicMock()
    fake_response.data = {"news": []}
    fake_client = MagicMock()
    fake_client.get_news.return_value = fake_response

    fetch_recent_headlines(fake_client, "AAPL")

    request = fake_client.get_news.call_args.args[0]
    assert request.start is None
    assert request.end is None
