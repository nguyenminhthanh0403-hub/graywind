"""Keyword-retrieval module for Graywind grounding facts.

The facts are a snapshot produced by scripts/extract_graywind_grounding.py;
no live reads are performed here.
"""
import json
import os
import re

_GROUNDING_PATH = os.path.join(os.path.dirname(__file__), "data", "graywind_grounding.json")

with open(_GROUNDING_PATH, encoding="utf-8") as f:
    _FACTS = json.load(f)["facts"]

MIN_SCORE = 1
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or", "in",
    "on", "for", "with", "what", "why", "how", "does", "do", "did", "it",
    "this", "that", "explain", "tell", "me", "about"
}


def _tokenize(text: str) -> set[str]:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", " ", text.lower())
    return {
        token
        for token in cleaned.split()
        if token not in STOPWORDS and len(token) > 1
    }


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """Keyword-match the query against Graywind's own decision/pending/
    watchlist facts (built at snapshot time by
    scripts/extract_graywind_grounding.py -- no live account read
    happens here or at request time).
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    hits_with_score = []
    for fact in _FACTS:
        haystack_tokens = set(fact["tags"]) | _tokenize(fact["text"])
        score = len(query_tokens & haystack_tokens)
        if score >= MIN_SCORE:
            hit = {
                "type": "graywind_fact",
                "id": fact["id"],
                "text": fact["text"],
            }
            hits_with_score.append((hit, score))

    hits_with_score.sort(key=lambda x: x[1], reverse=True)
    return [hit for hit, _ in hits_with_score[:top_k]]


def format_context(hits: list[dict]) -> str | None:
    if not hits:
        return None
    header = (
        "Live-ish state from your own Graywind trading bot (snapshot, may "
        "be stale by up to a build cycle -- not a live account read):"
    )
    lines = [header] + [f"- {hit['text']}" for hit in hits]
    return "\n".join(lines)
