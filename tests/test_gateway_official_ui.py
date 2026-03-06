from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_admin_ui_requires_api_key() -> None:
    resp = client.get("/admin/ui")
    assert resp.status_code == 401


def test_admin_ui_renders_official_ui_template() -> None:
    resp = client.get("/admin/ui", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert "Official UI" in resp.text
    assert "Market Intel Control Center" in resp.text


def test_email_validation_latest_requires_api_key() -> None:
    resp = client.get("/email-validation/latest")
    assert resp.status_code == 401


def test_email_validation_latest_proxies_to_run_ledger(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"status": "success", "window": "daily"}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/email-validation/latest?window=daily", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["item"]["status"] == "success"
    assert captured["base"] == "http://run-ledger-service:8011"
    assert captured["path"] == "/email-validation/latest"
    assert captured["params"]["window"] == "daily"


def test_executive_email_latest_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"executive_digest_sent": True}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/internal/email/executive/latest", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["item"]["executive_digest_sent"] is True
    assert captured["base"] == gateway_main.settings.AGENT_A_SERVICE_URL
    assert captured["path"] == "/internal/email/executive/latest"
