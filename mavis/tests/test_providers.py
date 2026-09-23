"""The brevity budget that keeps spoken answers short.

Length is latency for the avatar: voice conversion runs at ~1.5x realtime, so
every character the model writes is time Johnny stands there silent. These
tests pin both halves of that -- that asking for brevity works, and that not
asking leaves every other caller exactly as it was.
"""
import httpx
import pytest

import providers


class _FakeResponse:
    status_code = 200

    def __init__(self, captured):
        self._captured = captured

    def json(self):
        return {"choices": [{"message": {"content": "an answer"}}]}


class _FakeClient:
    """Captures the JSON body instead of calling Groq."""

    def __init__(self, captured, **kwargs):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self._captured.update(json)
        return _FakeResponse(self._captured)


@pytest.fixture
def sent(monkeypatch):
    captured = {}
    monkeypatch.setattr(providers, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        providers.httpx, "AsyncClient",
        lambda **kwargs: _FakeClient(captured, **kwargs),
    )
    return captured


@pytest.mark.asyncio
async def test_no_system_message_when_no_budget_is_given(sent):
    """The MCP wrapper and CLI must keep getting the prompt they always got."""
    await providers.groq_answer("what is the watchlist")

    roles = [m["role"] for m in sent["messages"]]
    assert roles == ["user"]


@pytest.mark.asyncio
async def test_a_budget_adds_a_system_message_before_the_question(sent):
    await providers.groq_answer("what is the watchlist", max_chars=200)

    messages = sent["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "200" in messages[0]["content"]
    assert "what is the watchlist" in messages[1]["content"]


def test_brevity_instruction_scales_with_the_budget():
    assert "1 short sentence" in providers._brevity_instruction(110)
    assert "4 short sentences" in providers._brevity_instruction(440)


def test_brevity_instruction_never_asks_for_zero_sentences():
    """A tiny budget must still ask for one sentence, not none."""
    assert "1 short sentence" in providers._brevity_instruction(10)


def test_brevity_instruction_forbids_markdown():
    """Answers are read aloud; bullet characters get spoken or mangled."""
    assert "markdown" in providers._brevity_instruction(200).lower()
