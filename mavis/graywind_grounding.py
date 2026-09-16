"""Keyword-retrieval module for Graywind grounding facts.

The facts are a snapshot produced by scripts/extract_graywind_grounding.py;
no live reads are performed here.
"""
import json
import os

from text_scoring import score_overlap, tokenize

_GROUNDING_PATH = os.path.join(os.path.dirname(__file__), "data", "graywind_grounding.json")

with open(_GROUNDING_PATH, encoding="utf-8") as f:
    _FACTS = json.load(f)["facts"]

# Fact text is ordinary English prose (e.g. "awaiting manual approval"), so
# a single overlap on a common word is not a real signal -- same reasoning
# as grounding.py's _STRONG_TERMS/MIN_SCORE=2. Tags are the deliberately
# curated match points (symbols, "watchlist", "decision", "pending",
# account names); a tag match counts double, a plain-text-only match once.
# "graywind" is a namespace marker build_facts() adds to every fact
# unconditionally -- a structural certainty, not a data-dependent one --
# so it carries zero discriminating power and is excluded by name. This
# is deliberately NOT "any tag not on every fact" (a document-frequency
# rule considered and rejected): with a single-symbol watchlist, that
# symbol's own tag would legitimately appear on every fact too, and a
# frequency-based rule would wrongly demote the one tag a query about
# that symbol most needs to hit strong on.
_STRUCTURAL_TAGS = {"graywind"}
_STRONG_TERMS = {tag for fact in _FACTS for tag in fact["tags"]} - _STRUCTURAL_TAGS
MIN_SCORE = 2


def retrieve(query: str, top_k: int = 5) -> list[dict]:
    """Keyword-match the query against Graywind's own decision/pending/
    watchlist facts (built at snapshot time by
    scripts/extract_graywind_grounding.py -- no live account read
    happens here or at request time).
    """
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    scored = []
    for fact in _FACTS:
        haystack_tokens = set(fact["tags"]) | tokenize(fact["text"])
        overlap = query_tokens & haystack_tokens
        score = score_overlap(overlap, _STRONG_TERMS)
        if score >= MIN_SCORE:
            scored.append((score, {
                "type": "graywind_fact",
                "id": fact["id"],
                "text": fact["text"],
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for score, item in scored[:top_k]]


def format_context(hits: list[dict]) -> str | None:
    if not hits:
        return None
    header = (
        "Live-ish state from your own Graywind trading bot (snapshot, may "
        "be stale by up to a build cycle -- not a live account read):"
    )
    lines = [header] + [f"- {hit['text']}" for hit in hits]
    return "\n".join(lines)
