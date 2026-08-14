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

Note on historical (backtest) queries: `NewsRequest.model_fields` (checked
the same way, via `NewsRequest.model_fields` on alpaca-py 0.44.0) confirms
a `start`/`end` pair, both typed `datetime.datetime | None` -- there is no
`symbol_or_symbols`-style trap here, the names are exactly `start`/`end`.
`fetch_recent_headlines` accepts an optional `as_of` (a `date`); when given,
it's converted to a `datetime` at midnight and passed as `end`, constraining
the query to headlines as of that reference date instead of always "now" --
this is what lets the backtester (Task 11) evaluate historical bars without
leaking future news into the sentiment score.
"""
from datetime import datetime

from alpaca.data.requests import NewsRequest
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

SENTIMENT_THRESHOLD = -0.2
_analyzer = SentimentIntensityAnalyzer()


class SentimentDataUnavailable(Exception):
    pass


def fetch_recent_headlines(news_client, symbol, limit=10, as_of=None):
    try:
        request_kwargs = {"symbols": symbol, "limit": limit}
        if as_of is not None:
            request_kwargs["end"] = datetime.combine(as_of, datetime.min.time())
        request = NewsRequest(**request_kwargs)
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
