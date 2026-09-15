import pytest
from fastapi.testclient import TestClient

import app as app_module
import auth
import rate_limit


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")


@pytest.fixture(autouse=True)
def reset_rate_limit():
    rate_limit._request_log.clear()


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_status_is_open_without_auth(client):
    resp = client.get("/status")

    assert resp.status_code == 200


def test_status_reports_whether_auth_is_configured(client, monkeypatch):
    resp = client.get("/status")
    assert resp.json()["auth_configured"] is True

    monkeypatch.setattr(auth, "MAVIS_API_KEY", None)
    resp = client.get("/status")
    assert resp.json()["auth_configured"] is False


def test_ask_without_api_key_is_rejected(client):
    resp = client.post("/ask", json={"query": "what is graywind's watchlist"})

    assert resp.status_code == 401


def test_ask_merges_bullion_and_graywind_citations(client, monkeypatch):
    async def fake_groq_answer(query, context=None):
        fake_groq_answer.seen_context = context
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)

    resp = client.post(
        "/ask",
        json={"query": "what is graywind's watchlist"},
        headers={"X-API-Key": "secret123"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "fake answer"
    assert any(c.get("id") == "watchlist" for c in body["citations"])
    assert "Graywind trading bot" in fake_groq_answer.seen_context


def test_ask_is_rate_limited(client, monkeypatch):
    async def fake_groq_answer(query, context=None):
        return "fake answer"

    monkeypatch.setattr(app_module, "groq_answer", fake_groq_answer)
    monkeypatch.setattr(rate_limit, "MAX_REQUESTS_PER_WINDOW", 1)

    headers = {"X-API-Key": "secret123"}
    ok = client.post("/ask", json={"query": "hi"}, headers=headers)
    blocked = client.post("/ask", json={"query": "hi"}, headers=headers)

    assert ok.status_code == 200
    assert blocked.status_code == 429
