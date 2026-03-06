from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway import main as gateway_main

client = TestClient(app)


def test_auth_login_rejects_invalid_credentials() -> None:
    resp = client.post("/auth/login", json={"username": "operator", "password": "nope"})
    assert resp.status_code == 401


def test_auth_login_sets_cookie_and_auth_me_works(monkeypatch) -> None:
    monkeypatch.setattr(gateway_main.settings, "OPERATOR_USERNAME", "operator")
    monkeypatch.setattr(gateway_main.settings, "OPERATOR_PASSWORD", "secret")
    monkeypatch.setattr(gateway_main.settings, "SESSION_SECRET", "unit-test-secret")
    monkeypatch.setattr(gateway_main.settings, "SESSION_COOKIE_NAME", "mip_session")
    monkeypatch.setattr(gateway_main.settings, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(gateway_main.settings, "SESSION_COOKIE_SAMESITE", "lax")

    login_resp = client.post("/auth/login", json={"username": "operator", "password": "secret"})
    assert login_resp.status_code == 200
    assert login_resp.json()["ok"] is True
    assert "mip_session" in login_resp.cookies

    me_resp = client.get("/auth/me", cookies={"mip_session": login_resp.cookies["mip_session"]})
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is True
    assert me_resp.json()["user"]["username"] == "operator"


def test_auth_logout_clears_session_cookie(monkeypatch) -> None:
    monkeypatch.setattr(gateway_main.settings, "SESSION_COOKIE_NAME", "mip_session")
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_cookie_session_allows_api_access(monkeypatch) -> None:
    monkeypatch.setattr(gateway_main.settings, "OPERATOR_USERNAME", "operator")
    monkeypatch.setattr(gateway_main.settings, "OPERATOR_PASSWORD", "secret")
    monkeypatch.setattr(gateway_main.settings, "SESSION_SECRET", "unit-test-secret")
    monkeypatch.setattr(gateway_main.settings, "SESSION_COOKIE_NAME", "mip_session")

    async def fake_forward_get(base: str, path: str, *, params=None):
        return {"items": []}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)

    login_resp = client.post("/auth/login", json={"username": "operator", "password": "secret"})
    cookie = login_resp.cookies.get("mip_session")
    assert cookie

    runs_resp = client.get("/runs?limit=5", cookies={"mip_session": cookie})
    assert runs_resp.status_code == 200
