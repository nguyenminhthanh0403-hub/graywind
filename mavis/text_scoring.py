STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "and", "or",
    "in", "on", "for", "with", "what", "why", "how", "does", "do", "did",
    "it", "this", "that", "explain", "tell", "me", "about",
}


def tokenize(text):
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


def score_overlap(overlap, strong_terms):
    """2 points per strong-term match (a specific, discriminating
    identifier), 1 point per plain-text match -- shared by grounding.py
    and graywind_grounding.py so a scoring/stopword tuning fix lands in
    one place instead of drifting between the two.
    """
    strong = overlap & strong_terms
    weak = overlap - strong_terms
    return 2 * len(strong) + len(weak)
