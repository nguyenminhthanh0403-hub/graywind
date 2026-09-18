"""Backend-calling logic for MAVIS's MCP tools.

Wraps the already-running /ask endpoint over HTTP -- this module does not
re-implement grounding, auth, or rate-limiting; it calls the endpoint that
already does that (see mavis/app.py). Any failure reaching or being
accepted by the backend is raised as ToolError, so an MCP client sees a
clean message instead of a raw httpx exception.
"""
import os

import httpx
from mcp.server.mcpserver.exceptions import ToolError


def _base_url() -> str:
    return os.environ.get("MAVIS_URL", "http://localhost:8000")


async def call_ask(query: str, *, client: httpx.AsyncClient | None = None) -> dict:
    """POST query to MAVIS's /ask endpoint and return the parsed JSON body.

    Pass `client` in tests (e.g. an httpx.AsyncClient built on a
    MockTransport); production callers omit it and a real client is
    created and closed around the single request.
    """
    base_url = _base_url()
    api_key = os.environ.get("MAVIS_API_KEY", "")
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    try:
        try:
            resp = await client.post(
                "/ask",
                json={"query": query},
                headers={"X-API-Key": api_key},
            )
        except httpx.ConnectError as exc:
            raise ToolError(f"backend not reachable at {base_url}") from exc

        if resp.status_code == 401:
            raise ToolError(
                "MAVIS_API_KEY was rejected by the backend (401) -- check "
                "the key configured in the MCP server's env"
            )
        if resp.status_code == 429:
            raise ToolError("MAVIS backend rate limit exceeded (429), try again shortly")
        if resp.status_code >= 500:
            raise ToolError(f"MAVIS backend returned {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()
    finally:
        if owns_client:
            await client.aclose()


def _format_citation(c: dict) -> str:
    kind = c.get("type")
    if kind == "node":
        return f"[{c.get('label', c.get('id'))}] {c.get('text', '')}"
    if kind == "link":
        return f"[{c.get('s')}->{c.get('t')}] {c.get('text', '')}"
    if kind == "graywind_fact":
        return c.get("text", "")
    return str(c)


def _format_answer(body: dict) -> str:
    answer = body.get("answer", "")
    citations = body.get("citations") or []
    if not citations:
        return answer
    lines = "\n".join(f"- {_format_citation(c)}" for c in citations)
    return f"{answer}\n\nCitations:\n{lines}"


async def ask_graywind(query: str) -> str:
    """Ask about Graywind's own live trading state: positions, tiers,
    gates, recent decisions, watchlist. Retrieval is merged with Bullion's
    map server-side, so citations may include both."""
    body = await call_ask(query)
    return _format_answer(body)


async def query_bullion(query: str) -> str:
    """Ask about Bullion's audited financial-system map: nodes, links,
    causal claims about markets and macro plumbing. Retrieval is merged
    with Graywind's trading-state facts server-side, so citations may
    include both."""
    body = await call_ask(query)
    return _format_answer(body)
