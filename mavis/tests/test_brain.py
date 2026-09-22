import httpx
import pytest

from avatar import brain


def _client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler),
                             base_url="http://localhost:8000")


@pytest.mark.asyncio
async def test_ask_returns_the_answer_text(monkeypatch):
    monkeypatch.setenv("MAVIS_API_KEY", "testkey")

    def handler(request):
        assert request.url.path == "/ask"
        assert request.headers["x-api-key"] == "testkey"
        return httpx.Response(200, json={"answer": "Night City burns.",
                                         "citations": []})

    client = _client_for(handler)
    try:
        assert await brain.ask("what's up", client=client) == "Night City burns."
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_long_answers_are_capped_at_a_sentence_boundary():
    """Voice conversion runs at ~1.4x realtime, so answer length is
    latency. Cutting mid-word would sound broken."""
    long_answer = ("This is a sentence. " * 80).strip()

    def handler(request):
        return httpx.Response(200, json={"answer": long_answer, "citations": []})

    client = _client_for(handler)
    try:
        result = await brain.ask("tell me everything", client=client)
    finally:
        await client.aclose()

    assert len(result) <= brain.MAX_ANSWER_CHARS
    assert result.endswith(".")


@pytest.mark.asyncio
async def test_backend_error_raises_brain_error():
    def handler(request):
        return httpx.Response(500, text="boom")

    client = _client_for(handler)
    try:
        with pytest.raises(brain.BrainError):
            await brain.ask("hello", client=client)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unreachable_backend_raises_brain_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = _client_for(handler)
    try:
        with pytest.raises(brain.BrainError):
            await brain.ask("hello", client=client)
    finally:
        await client.aclose()
