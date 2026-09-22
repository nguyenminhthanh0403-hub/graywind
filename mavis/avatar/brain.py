"""Ask the already-running MAVIS backend.

Direct HTTP rather than MCP: this is a GUI app on the same machine as the
server, so it calls /ask exactly the way mcp_tools.call_ask does, without
an MCP layer in between.

Answers are capped because voice conversion runs at roughly 1.4x realtime
-- a 20-second answer costs ~28 seconds of conversion, so length is
latency, not just verbosity.
"""
import os
import re

import httpx

MAX_ANSWER_CHARS = 420


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
            "/ask", json={"query": query},
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
