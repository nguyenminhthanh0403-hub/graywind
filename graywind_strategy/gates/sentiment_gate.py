"""Sentiment gate: blocks new trades when VADER's compound sentiment score
on recent Alpaca News headlines falls below a configured threshold. Fails
closed on fetch failure (SentimentDataUnavailable); a successful fetch that
finds no headlines is scored neutral (0.0), not treated as a failure.

Note on the alpaca-py API: `NewsRequest` (installed version 0.44.0) takes a
`symbols` field (a comma-separated string), not `symbol_or_symbols`. Passing
`symbol_or_symbols` does not raise -- pydantic silently drops the unknown
kwarg, leaving `symbols=None`, which would fetch news for all symbols instead
of the requested one. Verified via static inspection of the installed
`alpaca-py` package (NewsRequest.model_fields, NewsClient.get_news source,
NewsSet source); no live Alpaca API call was made since no credentials were
available in this environment. `response.data["news"]` and `article.headline`
were confirmed correct from NewsSet/News model source.
"""
from alpaca.data.requests import NewsRequest
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

SENTIMENT_THRESHOLD = -0.2
_analyzer = SentimentIntensityAnalyzer()


class SentimentDataUnavailable(Exception):
    pass


def fetch_recent_headlines(news_client, symbol, limit=10):
    try:
        request = NewsRequest(symbols=symbol, limit=limit)
        response = news_client.get_news(request)
        return [article.headline for article in response.data["news"]]
    except Exception as exc:
        raise SentimentDataUnavailable(str(exc)) from exc


def sentiment_score(headlines):
    if not headlines:
        return 0.0
    scores = [_analyzer.polarity_scores(h)["compound"] for h in headlines]
    return sum(scores) / len(scores)


def sentiment_gate(score, threshold=SENTIMENT_THRESHOLD):
    return score >= threshold
