"""Bullion macro-event shadow debate -- SHADOW MODE ONLY, cycle-level (not
per-symbol). Reads Bullion's market-wide news.json (Fed policy, geopolitics,
macro headlines -- distinct from news_debate.py's per-symbol headlines) and
logs a probability-weighted read of a handful of events once per trading
cycle. This module's output never gates a trade: pipeline.py::decide_trade()
has no code path into anything here. See
docs/superpowers/specs/2026-09-12-graywind-bullion-macro-debate-design.md.

Provider: same DeepSeek client (already wired for news_debate.py) -- no new
secret, no new dependency. See news_debate.py's module docstring for why
`extra_body={"thinking": {"type": "disabled"}}` is required on every call
(DeepSeek-v4-flash otherwise rejects a forced tool_choice with an HTTP 400).
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests

NEWS_DEBATE_MODEL = "deepseek-v4-flash"
NEWS_DEBATE_MAX_TOKENS = 1024

BULLION_NEWS_URL = "https://nguyenminhthanh0403-hub.github.io/claudekit/bullion-live-map/news.json"
STALENESS_CEILING_HOURS = 48

SUBMIT_EVENTS_TOOL_NAME = "submit_macro_events"


class MacroNewsUnavailable(Exception):
    pass


@dataclass
class MacroEvent:
    event: str
    probability: float
    implication: str


def fetch_bullion_headlines(session=requests):
    try:
        response = session.get(BULLION_NEWS_URL, timeout=10)
        response.raise_for_status()
        payload = response.json()
        generated_at = datetime.strptime(
            payload["generated_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        headlines = payload["headlines"]
    except MacroNewsUnavailable:
        raise
    except Exception as exc:
        raise MacroNewsUnavailable(str(exc)) from exc

    age = datetime.now(timezone.utc) - generated_at
    if age > timedelta(hours=STALENESS_CEILING_HOURS):
        raise MacroNewsUnavailable(
            f"Bullion news feed is {age} old, older than the "
            f"{STALENESS_CEILING_HOURS}h staleness ceiling"
        )
    return headlines
