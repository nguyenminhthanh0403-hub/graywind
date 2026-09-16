import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import auth


def make_app():
    app = FastAPI()

    @app.get("/protected")
    def protected(api_key: str = Depends(auth.require_api_key)):
        return {"ok": True}

    return app


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected")

    assert resp.status_code == 401


def test_wrong_key_is_rejected(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "wrong"})

    assert resp.status_code == 401


def test_correct_key_is_accepted(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "secret123"})

    assert resp.status_code == 200


def test_unset_server_key_fails_closed(monkeypatch):
    monkeypatch.setattr(auth, "MAVIS_API_KEY", None)
    client = TestClient(make_app())

    resp = client.get("/protected", headers={"X-API-Key": "anything"})

    assert resp.status_code == 500


def test_non_ascii_key_is_rejected_cleanly_not_a_server_error(monkeypatch):
    # A real server decodes raw header bytes as latin-1 and can hand this
    # function a non-ASCII str; httpx's TestClient refuses to send one as a
    # plain header value, so this calls the dependency directly.
    monkeypatch.setattr(auth, "MAVIS_API_KEY", "secret123")

    with pytest.raises(HTTPException) as exc_info:
        auth.require_api_key(x_api_key="sécret")

    assert exc_info.value.status_code == 401
