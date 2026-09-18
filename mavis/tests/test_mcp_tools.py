import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import mcp_tools


def _client_for(handler):
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_call_ask_returns_parsed_json_on_success(monkeypatch):
    monkeypatch.setenv("MAVIS_API_KEY", "testkey")
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
