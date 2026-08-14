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

IMPORTANT: `start` is not optional in practice even though it's typed
`Optional`. Per `NewsRequest`'s docstring (`inspect.getsource`), when `start`
is omitted the server defaults it to the beginning of the *current* day --
not the beginning of the requested `end` date. Passing only `end` for a
historical `as_of` therefore produces an inverted server-side window
(`[today, as_of]` when `as_of` is in the past), which returns either zero
articles (silently makes the gate always pass) or a 4xx error (always
blocks) -- neither is "evaluate sentiment as of this historical date". This
was caught in review by serializing the built request
(`request.to_request_fields()`) and confirming no `start` key was present.

`fetch_recent_headlines` accepts an optional `as_of` (a `date`); when given,
it sets both `start` (a `SENTIMENT_LOOKBACK_DAYS`-day lookback window before
`as_of`, at midnight) and `end` (the end of `as_of`'s own day, `time.max`, so
that day's own news is in-sample for a bar-close decision) -- this is what
lets the backtester (Task 11) evaluate historical bars without leaking
future news into the sentiment score, and without silently defaulting to an
inverted or "today-anchored" window.
"""
from datetime import datetime, time, timedelta

from alpaca.data.requests import NewsRequest
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

SENTIMENT_THRESHOLD = -0.2
SENTIMENT_LOOKBACK_DAYS = 3
_analyzer = SentimentIntensityAnalyzer()


class SentimentDataUnavailable(Exception):
    pass


def fetch_recent_headlines(news_client, symbol, limit=10, as_of=None):
    try:
        request_kwargs = {"symbols": symbol, "limit": limit}
        if as_of is not None:
            request_kwargs["start"] = datetime.combine(
                as_of - timedelta(days=SENTIMENT_LOOKBACK_DAYS), time.min
            )
            request_kwargs["end"] = datetime.combine(as_of, time.max)
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
