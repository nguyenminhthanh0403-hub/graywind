"""Ask the already-running MAVIS backend.

Direct HTTP rather than MCP: this is a GUI app on the same machine as the
server, so it calls /ask exactly the way mcp_tools.call_ask does, without
an MCP layer in between.

Answers are capped because voice conversion runs at roughly 1.5x realtime
-- a 20-second answer costs ~30 seconds of conversion, so length is
latency, not just verbosity.
"""
import os
import re

import httpx

# Measured 2026-09-22 on this machine: 386 characters of real answer text is
# 21.9s of `say -v Tom` audio, i.e. ~17.6 chars/sec. ChatterboxVC then converts
# at ~1.5x realtime, so the cap translates almost linearly into how long he
# stands there silently before speaking:
#
#     420 chars -> ~24s of speech -> ~36s of conversion   (the owner: "kinda long")
#     200 chars -> ~11s of speech -> ~17s of conversion
#
# Everything else in a turn -- trailing-silence detection, STT, /ask -- is ~4s
# combined, so this constant is the single biggest lever on perceived latency
# until chunked conversion exists. Lowered 420 -> 200 on 2026-09-22.
#
# Override without editing code, to tune it against a real run:
#     export MAVIS_MAX_ANSWER_CHARS=300
DEFAULT_MAX_ANSWER_CHARS = 200


def _budget_from_env(raw) -> int:
    """Parse the override, falling back rather than refusing to import.

    A bare int() here would raise on an empty or malformed value *at import
    time*, so the whole avatar would fail to start over a mistyped tuning knob.
    A LaunchAgent plist is exactly where an empty env value comes from, and
    every other failure path in this project degrades loudly instead of dying.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ANSWER_CHARS
    return value if value > 0 else DEFAULT_MAX_ANSWER_CHARS


MAX_ANSWER_CHARS = _budget_from_env(os.environ.get("MAVIS_MAX_ANSWER_CHARS"))


class BrainError(RuntimeError):
    pass


def _base_url() -> str:
    return os.environ.get("MAVIS_URL", "http://localhost:8000")


def cap(answer: str) -> str:
    """Trim to MAX_ANSWER_CHARS at a sentence boundary where possible."""
    answer = answer.strip()
    if len(answer) <= MAX_ANSWER_CHARS:
        return answer
    window = answer[:MAX_ANSWER_CHARS]
    sentences = re.findall(r".+?[.!?](?:\s|$)", window, flags=re.S)
    if sentences:
        return "".join(sentences).strip()
    return window.rsplit(" ", 1)[0].strip()


async def ask(query: str, *, client: httpx.AsyncClient | None = None) -> str:
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(base_url=_base_url(), timeout=60.0)
    try:
        resp = await client.post(
            # max_chars asks the backend to *write* short; cap() below is the
            # backstop for when it ignores that. Truncation alone stops him
            # mid-thought, which sounds worse than a short answer.
            "/ask", json={"query": query, "max_chars": MAX_ANSWER_CHARS},
            headers={"X-API-Key": os.environ.get("MAVIS_API_KEY", "")},
        )
    except httpx.RequestError as exc:
        raise BrainError(f"MAVIS backend unreachable: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code != 200:
        raise BrainError(f"MAVIS backend returned {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise BrainError("MAVIS backend returned a non-JSON response") from exc
    return cap(body.get("answer", ""))
