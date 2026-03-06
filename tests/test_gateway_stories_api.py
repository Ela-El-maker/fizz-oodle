from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_gateway_stories_latest_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"scope": "market", "headline": "h"}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get(
        "/stories/latest?scope=market&context=prices&force_regenerate=false",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["item"]["scope"] == "market"
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/stories/latest"
    assert captured["params"]["scope"] == "market"
    assert captured["params"]["context"] == "prices"
    assert captured["params"]["force_regenerate"] is False


def test_gateway_stories_list_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"items": []}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get(
        "/stories?scope=announcement&status=ready&limit=10&offset=5",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/stories"
    assert captured["params"]["scope"] == "announcement"
    assert captured["params"]["status"] == "ready"
    assert captured["params"]["limit"] == 10
    assert captured["params"]["offset"] == 5


def test_gateway_story_by_id_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"card_id": "c1"}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/stories/c1", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["item"]["card_id"] == "c1"
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/stories/c1"
    assert captured["params"] is None


def test_gateway_stories_rebuild_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_post(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"accepted": True}

    monkeypatch.setattr(gateway_main, "_forward_post", fake_forward_post)
    resp = client.post("/stories/rebuild?force_regenerate=true", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/stories/rebuild"
    assert captured["params"]["force_regenerate"] is True
