import json
import os

_GROUNDING_PATH = os.path.join(os.path.dirname(__file__), "data", "bullion_grounding.json")

with open(_GROUNDING_PATH) as f:
    _DATA = json.load(f)

_NODES = _DATA["nodes"]
_LINKS = _DATA["links"]
_LABEL_BY_ID = {n["id"]: n["label"] for n in _NODES}

# Node ids are short, specific finance terms (fed, repo, vix, sec...) -- a
# single match on one of these is a strong signal. A single match on any
# other shared word (e.g. "good", "name") is not, and would otherwise
# false-positive constantly since node/link prose is ordinary English text.
_STRONG_TERMS = set(_LABEL_BY_ID.keys())
MIN_SCORE = 2

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or",
    "in", "on", "for", "with", "what", "why", "how", "does", "do", "did",
    "it", "this", "that", "explain", "tell", "me", "about",
}


def _tokenize(text):
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def retrieve(query, top_k=5):
    """Keyword-match the query against Bullion's node/link claims.

    Linear scan over 39 nodes / 93 links — small enough that no index is
    worth building. A hit means the query is grounded in the audited map,
    surfaced back to the caller as citations.
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    def score_overlap(overlap):
        strong = overlap & _STRONG_TERMS
        weak = overlap - _STRONG_TERMS
        return 2 * len(strong) + len(weak)

    scored = []

    for n in _NODES:
        haystack = " ".join([n["id"], n["label"], *n["beginner"], *n["expert"]])
        overlap = q_tokens & _tokenize(haystack)
        score = score_overlap(overlap)
        if n["label"].lower() in query.lower():
            score += 2
        if score >= MIN_SCORE:
            scored.append((score, {
                "type": "node",
                "id": n["id"],
                "label": n["label"],
                "text": " ".join(n["expert"] or n["beginner"]),
            }))

    for l in _LINKS:
        s_label = _LABEL_BY_ID.get(l["s"], l["s"])
        t_label = _LABEL_BY_ID.get(l["t"], l["t"])
        haystack = " ".join([s_label, t_label, l["why"] or "", l["stat"] or ""])
        overlap = q_tokens & _tokenize(haystack)
        score = score_overlap(overlap)
        if score >= MIN_SCORE:
            scored.append((score, {
                "type": "link",
                "s": l["s"],
                "t": l["t"],
                "sign": l["sign"],
                "conf": l["conf"],
                "text": f"{s_label} -> {t_label}: {l['why']} ({l['stat']})",
            }))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for score, item in scored[:top_k]]


def format_context(hits):
    if not hits:
        return None
    lines = ["Grounding from the audited Bullion financial-system map (cite this, don't improvise numbers):"]
    for h in hits:
        if h["type"] == "node":
            lines.append(f"- [{h['label']}] {h['text']}")
        else:
            lines.append(f"- [{h['s']}->{h['t']}, {h['conf']}] {h['text']}")
    return "\n".join(lines)
