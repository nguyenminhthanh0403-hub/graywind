import os
import time
from collections import defaultdict

from fastapi import HTTPException

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = int(os.environ.get("MAVIS_RATE_LIMIT_PER_MINUTE", "20"))

_request_log = defaultdict(list)


def check_rate_limit(key):
    """Fixed-window limiter: at most MAX_REQUESTS_PER_WINDOW calls per key
    per WINDOW_SECONDS. In-memory and per-process -- fine for a single-VPS
    FastAPI instance, not for multiple workers/instances.

    auth.require_api_key only ever returns the one configured
    MAVIS_API_KEY (a single shared secret, not per-caller credentials),
    so in practice this is one global bucket shared by every legitimate
    caller, not an isolated quota per person/script -- "per key" is
    accurate about what this function does, not about how many distinct
    keys exist today.
    """
    now = time.monotonic()
    window_start = now - WINDOW_SECONDS

    recent = [t for t in _request_log[key] if t > window_start]
    if len(recent) >= MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(429, "rate limit exceeded, try again shortly")

    recent.append(now)
    _request_log[key] = recent
