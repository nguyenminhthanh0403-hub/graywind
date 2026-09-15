import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_ask_merges_bullion_and_graywind_citations(client, monkeypatch):
    async def fake_groq_answer(query, context=None):
        fake_groq_answer.seen_context = context
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)

    resp = client.post("/ask", json={"query": "what is graywind's watchlist"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "fake answer"
    assert any(c.get("id") == "watchlist" for c in body["citations"])
    assert "Graywind trading bot" in fake_groq_answer.seen_context
