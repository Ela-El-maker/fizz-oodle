from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_gateway_announcements_insight_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"announcement_id": "abc", "item": {"version": "v1"}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get(
        "/announcements/abc/insight?refresh_context_if_needed=true&force_regenerate=false",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["announcement_id"] == "abc"
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/announcements/abc/insight"
    assert captured["params"]["refresh_context_if_needed"] is True
    assert captured["params"]["force_regenerate"] is False


def test_gateway_announcements_context_refresh_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_post(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"announcement_id": "abc", "refresh": {"refreshed": True}}

    monkeypatch.setattr(gateway_main, "_forward_post", fake_forward_post)
    resp = client.post("/announcements/abc/context/refresh", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["refresh"]["refreshed"] is True
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/announcements/abc/context/refresh"
    assert captured["params"] is None
