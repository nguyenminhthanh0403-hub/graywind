# MAVIS MCP Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MAVIS's existing `/ask` endpoint callable from Claude CLI by wrapping it as an MCP server exposing `ask_graywind` and `query_bullion` tools.

**Architecture:** Two new files in `mavis/`. `mcp_tools.py` holds the pure async logic — HTTP calls to a running MAVIS instance's `/ask` endpoint via `httpx`, with backend failures translated into `mcp.server.mcpserver.exceptions.ToolError` (clean message, no traceback reaches the calling model). `mcp_server.py` is a thin wiring layer — constructs an `MCPServer`, registers the two functions from `mcp_tools.py` as tools with distinct descriptions, and runs over stdio. Both tools call the same merged `/ask` retrieval (no backend split exists, and none is being added) — their descriptions say so honestly and differ in which kind of question each is meant for, not in what data they can reach.

**Tech Stack:** Python 3.14, `mcp` 2.2.0 (`mcp.server.mcpserver.MCPServer`, the current API — NOT the `mcp.server.fastmcp.FastMCP` name from `mcp` 1.x, which does not exist in 2.x), `httpx` 0.28.1 (already a dependency), `pytest` 9.1.1.

**Spec:** `docs/superpowers/graywind-mavis-mcp-wrapper-handoff.md` (Night 3 scope and traps) and `~/Downloads/mavis-cloud-avatar-plan.md` Section 2 (architecture diagram) and Section 3b (tool names). Both already read; this plan implements Night 3 only.

## Global Constraints

- No changes to `mavis/grounding.py`, `mavis/graywind_grounding.py`, `mavis/auth.py`, `mavis/rate_limit.py`, or `mavis/app.py` — Night 3 wraps `/ask`, it does not touch grounding/auth/rate-limiting logic.
- MAVIS stays local-only this session — no VPS deployment, no changes to how `/ask` is hosted.
- `mcp==2.2.0` (already installed in `mavis/.venv`, confirmed clean install on this venv's Python 3.14.6 — do not pin `mcp<2`, that pulls the deprecated `FastMCP` API this plan does not use).
- Any failure calling the backend (connection refused, 401, 429, 5xx) must reach the MCP client as a `ToolError` with a plain-English message — never a raw `httpx` exception or Python traceback.
- `MAVIS_URL` (default `http://localhost:8000`) and `MAVIS_API_KEY` are read from `os.environ` only, at call time, not cached at import time — a stdio MCP server spawned by Claude CLI gets its env from the CLI's own `-e` config, not the interactive shell.
- Server registration happens via `claude mcp add` (the CLI writes its own config); this plan never hand-edits `.mcp.json` or `~/.claude.json`.
- Every new file uses unqualified same-directory imports (`import mcp_tools`, not `from mavis.mcp_tools import ...`) to match this codebase's existing convention (see `app.py`'s `import auth`, `import grounding`).

---

## Task 1: Add the `mcp` dependency

**Files:**
- Modify: `mavis/requirements.txt`

**Interfaces:**
- Produces: `mcp` importable in the venv at the pinned version, used by Task 3.

- [ ] **Step 1: Pin the dependency**

Add this line to `mavis/requirements.txt` (alphabetical order doesn't matter here, this file is otherwise unordered):

```
mcp==2.2.0
```

- [ ] **Step 2: Verify it's already installed and matches the pin**

Run: `cd mavis && source .venv/bin/activate && pip show mcp | grep Version`
Expected: `Version: 2.2.0` (it was installed during planning to verify the API; this step just confirms `requirements.txt` now matches what's actually in the venv).

- [ ] **Step 3: Commit**

```bash
cd mavis
git add requirements.txt
git commit -m "chore(mavis): pin mcp SDK dependency for Night 3 MCP wrapper"
```

---

## Task 2: `mcp_tools.py` — backend-calling logic

**Files:**
- Create: `mavis/mcp_tools.py`
- Test: `mavis/tests/test_mcp_tools.py`

**Interfaces:**
- Consumes: nothing from other new files. Reads `MAVIS_URL` / `MAVIS_API_KEY` from `os.environ` at call time. Depends on `httpx` (already installed) and `mcp.server.mcpserver.exceptions.ToolError`.
- Produces (for Task 3):
  - `async def ask_graywind(query: str) -> str`
  - `async def query_bullion(query: str) -> str`
  - Both raise `mcp.server.mcpserver.exceptions.ToolError` on any backend failure; both return plain text (answer, plus a "Citations:" block if any citations came back) on success.

- [ ] **Step 1: Write the failing tests**

Create `mavis/tests/test_mcp_tools.py`:

```python
import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import mcp_tools


def _client_for(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_call_ask_returns_parsed_json_on_success():
    def handler(request):
        assert request.url.path == "/ask"
        assert request.headers["x-api-key"] == "testkey"
        return httpx.Response(200, json={"answer": "the sky is blue", "citations": []})

    client = _client_for(handler)
    try:
        body = await mcp_tools.call_ask("why is the sky blue", client=client)
    finally:
        await client.aclose()

    assert body == {"answer": "the sky is blue", "citations": []}


@pytest.mark.asyncio
async def test_call_ask_sends_api_key_from_env(monkeypatch):
    monkeypatch.setenv("MAVIS_API_KEY", "envkey123")
    seen = {}

    def handler(request):
        seen["key"] = request.headers["x-api-key"]
        return httpx.Response(200, json={"answer": "ok", "citations": []})

    client = _client_for(handler)
    try:
        await mcp_tools.call_ask("q", client=client)
    finally:
        await client.aclose()

    assert seen["key"] == "envkey123"


@pytest.mark.asyncio
async def test_call_ask_raises_tool_error_on_connect_failure():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = _client_for(handler)
    try:
        with pytest.raises(ToolError, match="backend not reachable at"):
            await mcp_tools.call_ask("q", client=client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_call_ask_raises_tool_error_on_401():
    def handler(request):
        return httpx.Response(401, json={"detail": "invalid or missing X-API-Key header"})

    client = _client_for(handler)
    try:
        with pytest.raises(ToolError, match="401"):
            await mcp_tools.call_ask("q", client=client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_call_ask_raises_tool_error_on_429():
    def handler(request):
        return httpx.Response(429, json={"detail": "rate limit exceeded, try again shortly"})

    client = _client_for(handler)
    try:
        with pytest.raises(ToolError, match="429"):
            await mcp_tools.call_ask("q", client=client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_call_ask_raises_tool_error_on_500():
    def handler(request):
        return httpx.Response(500, text="internal server error")

    client = _client_for(handler)
    try:
        with pytest.raises(ToolError, match="500"):
            await mcp_tools.call_ask("q", client=client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_ask_graywind_formats_answer_with_citations(monkeypatch):
    async def fake_call_ask(query, *, client=None):
        return {
            "answer": "graywind holds AAPL",
            "citations": [
                {"type": "graywind_fact", "id": "f1", "text": "tier 2 holds AAPL"},
                {"type": "node", "id": "vix", "label": "VIX", "text": "volatility index"},
                {"type": "link", "s": "fed", "t": "repo", "text": "fed -> repo: liquidity (weak)"},
            ],
        }

    monkeypatch.setattr(mcp_tools, "call_ask", fake_call_ask)

    result = await mcp_tools.ask_graywind("what does graywind hold")

    assert "graywind holds AAPL" in result
    assert "Citations:" in result
    assert "tier 2 holds AAPL" in result
    assert "[VIX] volatility index" in result
    assert "[fed->repo]" in result


@pytest.mark.asyncio
async def test_query_bullion_omits_citations_block_when_empty(monkeypatch):
    async def fake_call_ask(query, *, client=None):
        return {"answer": "no grounded match", "citations": []}

    monkeypatch.setattr(mcp_tools, "call_ask", fake_call_ask)

    result = await mcp_tools.query_bullion("some obscure query")

    assert result == "no grounded match"
    assert "Citations:" not in result
```

- [ ] **Step 2: Add `pytest-asyncio` and configure it**

`mavis/` has no `pytest.ini`/`pyproject.toml`/`setup.cfg` of its own today (the repo-root `pytest.ini` at `~/Projects/graywind/pytest.ini` doesn't apply here — pytest config is per-directory-tree) and no async tests exist yet (existing tests are all sync `TestClient` calls). Add `pytest-asyncio==1.4.0` to `mavis/requirements-dev.txt`, install it:

```bash
cd mavis && source .venv/bin/activate && pip install pytest-asyncio==1.4.0
```

Then create `mavis/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_mcp_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_tools'` (file doesn't exist yet).

- [ ] **Step 4: Write `mavis/mcp_tools.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_mcp_tools.py -v`
Expected: 8 passed.

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `cd mavis && .venv/bin/python -m pytest -q`
Expected: 44 passed (36 existing + 8 new).

- [ ] **Step 7: Commit**

```bash
cd mavis
git add mcp_tools.py tests/test_mcp_tools.py requirements-dev.txt pytest.ini
git commit -m "feat(mavis): add MCP tool logic wrapping the /ask endpoint"
```

---

## Task 3: `mcp_server.py` — MCP server wiring and entrypoint

**Files:**
- Create: `mavis/mcp_server.py`
- Test: `mavis/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `mcp_tools.ask_graywind`, `mcp_tools.query_bullion` (from Task 2, unchanged signatures).
- Produces: a module-level `mcp` object (`mcp.server.mcpserver.MCPServer`) with both tools registered, and a `python mcp_server.py` entrypoint that runs it over stdio. This is what Task 4 registers with `claude mcp add`.

- [ ] **Step 1: Write the failing test**

Create `mavis/tests/test_mcp_server.py`:

```python
import pytest

import mcp_server


@pytest.mark.asyncio
async def test_both_tools_are_registered_with_distinct_descriptions():
    tools = await mcp_server.mcp.list_tools()
    names = {t.name for t in tools}

    assert names == {"ask_graywind", "query_bullion"}

    by_name = {t.name: t for t in tools}
    assert "Graywind" in by_name["ask_graywind"].description
    assert "Bullion" in by_name["query_bullion"].description
    # Both descriptions must be honest that retrieval is merged -- neither
    # tool can see only its own namesake's data.
    assert "merged" in by_name["ask_graywind"].description.lower()
    assert "merged" in by_name["query_bullion"].description.lower()


def test_server_name_is_mavis():
    assert mcp_server.mcp.name == "mavis"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server'`.

- [ ] **Step 3: Write `mavis/mcp_server.py`**

```python
"""MCP server exposing MAVIS's /ask endpoint as two tools.

Run directly (`python mcp_server.py`) to serve over stdio -- this is what
`claude mcp add` points at. Registration lives outside this repo, in
Claude CLI's own MCP config (see docs/superpowers/plans/2026-09-18-mavis-mcp-wrapper.md
Task 4); this file never touches that config itself.
"""
from mcp.server.mcpserver import MCPServer

import mcp_tools

mcp = MCPServer(name="mavis")

mcp.add_tool(
    mcp_tools.ask_graywind,
    name="ask_graywind",
    description=(
        "Ask about Graywind's own live trading state: positions, tiers, "
        "gates, recent decisions, watchlist. Retrieval is merged with "
        "Bullion's financial-system map server-side, so citations may "
        "include both -- pick this tool when the question is really "
        "about Graywind's trading, not the broader financial system."
    ),
)

mcp.add_tool(
    mcp_tools.query_bullion,
    name="query_bullion",
    description=(
        "Ask about Bullion's audited financial-system map: nodes, links, "
        "causal claims about markets and macro plumbing. Retrieval is "
        "merged with Graywind's own trading-state facts server-side, so "
        "citations may include both -- pick this tool when the question "
        "is really about the financial system, not Graywind's trading."
    ),
)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mavis && .venv/bin/python -m pytest tests/test_mcp_server.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full suite**

Run: `cd mavis && .venv/bin/python -m pytest -q`
Expected: 46 passed (44 from Task 2 + 2 new).

- [ ] **Step 6: Commit**

```bash
cd mavis
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat(mavis): wire ask_graywind/query_bullion as an MCP server"
```

---

## Task 4: Manual live verification and CLI registration

This task is not TDD — it's the real end-to-end check this project's prior MAVIS sessions have each relied on (per the handoff: "every prior MAVIS session's real bugs were caught this way, not by unit tests alone"). No code changes; if something's broken here, fix it in Task 2 or 3 and re-run this task, don't patch around it here.

**Files:** none created or modified.

- [ ] **Step 1: Start a real MAVIS server**

```bash
cd mavis
source ~/.zshrc && source .venv/bin/activate
export MAVIS_API_KEY=devlocal
uvicorn app:app --port 8000 &
```

Confirm it's up: `curl -s localhost:8000/status` should return `{"ok":true,...}`.

- [ ] **Step 2: Register the MCP server with Claude CLI**

```bash
claude mcp add mavis \
  -e MAVIS_API_KEY=devlocal \
  -e MAVIS_URL=http://localhost:8000 \
  -- /Users/thanhnguyen/Projects/graywind/mavis/.venv/bin/python \
     /Users/thanhnguyen/Projects/graywind/mavis/mcp_server.py
```

Using the venv's absolute `python` path (not a bare `python`/`python3`) matters here: the CLI spawns this as a fresh subprocess with only the `-e` env vars above, not your activated shell, so it must resolve `mcp`/`httpx` from the venv on its own.

Verify registration: `claude mcp list` should show `mavis`.

- [ ] **Step 3: Call it live from Claude CLI**

Start a fresh `claude` session (or `claude mcp get mavis` to sanity-check config first), then actually invoke one of the tools — e.g. ask the session a question that should route to `ask_graywind` or `query_bullion` — and confirm:
- A real answer comes back (not a connection/auth error).
- If the query matches grounding data, citations appear in the response text.

- [ ] **Step 4: Confirm the clean-error path (unplug the backend)**

```bash
kill %1  # stop the uvicorn job from Step 1
```

Call an `ask_graywind`/`query_bullion` tool again from the same Claude CLI session. Expected: the model reports a plain message like "backend not reachable at http://localhost:8000" — not a Python traceback or generic "Error executing tool" with no detail. This is the live confirmation of Task 2's `ToolError` handling actually reaching the client over the real stdio transport (the in-process `mcp.call_tool()` API re-raises `ToolError` directly rather than converting it — only the real request-handling layer used over stdio converts it to a clean `is_error=True` result, so this is the one check that can't be done as a unit test).

- [ ] **Step 5: Restart the backend and leave it running or stop it, your call**

```bash
cd mavis && source .venv/bin/activate && export MAVIS_API_KEY=devlocal
uvicorn app:app --port 8000 &
```

(Or leave it stopped — nothing else in this plan depends on it running continuously.)

- [ ] **Step 6: Record the outcome**

Note in the SDD progress ledger (`.superpowers/sdd/2026-09-18-mavis-mcp-wrapper/progress.md`) whether Steps 3 and 4 passed as expected, and paste the actual tool response text observed in Step 3 (this is the evidence a resuming session would otherwise have to redo).

---

## Self-Review Notes

- **Spec coverage:** Original plan §3b asked for an MCP wrapper exposing `ask_graywind`/`query_bullion` over the existing `/ask` endpoint (Tasks 2–3), callable from Claude CLI (Task 4). Handoff's correction about Fable/Anthropic credit is respected — nothing in this plan touches `providers.py` or adds any Anthropic API call. Handoff's "no changes to grounding/auth/rate-limiting" is respected — Tasks 2–3 only add new files. Handoff's "clean error, not a traceback" trap is covered by `ToolError` (Task 2) and verified live (Task 4, Step 4). Handoff's "stdio server doesn't inherit shell env" trap is covered by reading env at call time (Task 2) and passing `-e` flags explicitly in `claude mcp add` (Task 4).
- **Deferred by design, not an oversight:** migrating `data/*.json` grounding snapshots to a non-JSON format, and the Night 4 avatar frontend — both explicitly out of scope per this session's discussion, tracked as follow-ups, not tasks here.
- **Type/interface consistency:** `mcp_tools.ask_graywind`/`query_bullion` signatures (`async def name(query: str) -> str`) are identical between where Task 2 defines them and where Task 3 registers them via `mcp.add_tool`. `call_ask`'s `client` keyword-only param (Task 2) is used consistently across all 8 of its tests.
- **No placeholders:** every step above has literal file contents or literal shell commands — no "TBD"/"similar to Task N" left in.
