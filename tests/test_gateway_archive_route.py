from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway.main import app
from services.gateway import main as gateway_main

client = TestClient(app)


def test_gateway_archive_latest_requires_api_key() -> None:
    resp = client.get("/archive/latest")
    assert resp.status_code == 401


def test_gateway_archive_latest_proxies_to_agent_e(monkeypatch) -> None:
    captured = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/archive/latest?run_type=monthly", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["path"] == "/archive/latest"
    assert captured["params"]["run_type"] == "monthly"
