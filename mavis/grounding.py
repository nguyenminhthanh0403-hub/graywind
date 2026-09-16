import json
import os
import re

from text_scoring import score_overlap, tokenize

_GROUNDING_PATH = os.path.join(os.path.dirname(__file__), "data", "bullion_grounding.json")

with open(_GROUNDING_PATH) as f:
    _DATA = json.load(f)

_NODES = _DATA["nodes"]
_LINKS = _DATA["links"]
_LABEL_BY_ID = {n["id"]: n["label"] for n in _NODES}

# Whole-word, contiguous-phrase match on a node's human-readable label
# (e.g. "Yield Curve"), precompiled once. An unordered token-subset check
# was tried and rejected: it let unrelated multi-word co-occurrences (e.g.
# "farmers curve their yield every season" containing both "yield" and
# "curve" separately) trigger the bonus with no real relation to the node.
_LABEL_PATTERNS = {
    n["id"]: re.compile(r"\b" + re.escape(n["label"].lower()) + r"\b")
    for n in _NODES
}

# Node ids are short, specific finance terms (fed, repo, vix, sec...) -- a
# single match on one of these is a strong signal. A single match on any
# other shared word (e.g. "good", "name") is not, and would otherwise
# false-positive constantly since node/link prose is ordinary English text.
# Tokenized (not the raw id string): an underscore-joined id like "dxy_fx"
# would otherwise never appear in a tokenized query at all, since tokenize()
# splits on "_", permanently dead-ending that id's strong-match bonus.
_STRONG_TERMS = {token for node_id in _LABEL_BY_ID for token in tokenize(node_id)}
MIN_SCORE = 2


def retrieve(query, top_k=5):
    """Keyword-match the query against Bullion's node/link claims.

    Linear scan over 39 nodes / 93 links — small enough that no index is
    worth building. A hit means the query is grounded in the audited map,
    surfaced back to the caller as citations.
    """
    q_tokens = tokenize(query)
    if not q_tokens:
        return []

    query_lower = query.lower()
    scored = []

    for n in _NODES:
        haystack = " ".join([n["id"], n["label"], *n["beginner"], *n["expert"]])
        overlap = q_tokens & tokenize(haystack)
        score = score_overlap(overlap, _STRONG_TERMS)
        if _LABEL_PATTERNS[n["id"]].search(query_lower):
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
        overlap = q_tokens & tokenize(haystack)
        score = score_overlap(overlap, _STRONG_TERMS)
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
