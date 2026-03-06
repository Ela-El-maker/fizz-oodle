from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_admin_email_validation_requires_api_key() -> None:
    resp = client.post("/admin/email-validation/run?window=daily")
    assert resp.status_code == 401


def test_admin_email_validation_run_forwards_to_orchestrator(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(gateway_main.settings, "EMAIL_VALIDATION_RECIPIENTS", "qa@example.com")

    async def fake_run_email_validation(*, window: str, force: bool, recipients_override: str):
        captured["window"] = window
        captured["force"] = force
        captured["recipients_override"] = recipients_override
        return {"validation_run_id": "v-1", "status": "success"}

    monkeypatch.setattr(gateway_main, "run_email_validation", fake_run_email_validation)

    resp = client.post(
        "/admin/email-validation/run?window=weekly&force=true",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["validation_run_id"] == "v-1"
    assert captured == {
        "window": "weekly",
        "force": True,
        "recipients_override": "qa@example.com",
    }


def test_internal_email_validation_requires_internal_api_key() -> None:
    resp = client.post("/internal/ops/email-validation/run?window=daily")
    assert resp.status_code == 401


def test_internal_email_validation_run_forwards_to_orchestrator(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(gateway_main.settings, "EMAIL_VALIDATION_RECIPIENTS", "qa@example.com")

    async def fake_run_email_validation(*, window: str, force: bool, recipients_override: str):
        captured["window"] = window
        captured["force"] = force
        captured["recipients_override"] = recipients_override
        return {"validation_run_id": "v-2", "status": "partial"}

    monkeypatch.setattr(gateway_main, "run_email_validation", fake_run_email_validation)

    resp = client.post(
        "/internal/ops/email-validation/run?window=daily&force=false",
        headers={"x-internal-api-key": "internal-change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["validation_run_id"] == "v-2"
    assert captured == {
        "window": "daily",
        "force": False,
        "recipients_override": "qa@example.com",
    }


def test_run_agent_passes_email_recipients_override(monkeypatch) -> None:
    captured: dict = {}

    async def fake_publish_run_command(**kwargs):
        captured.update(kwargs)
        return {"requested_at": "2026-03-02T00:00:00+00:00"}

    monkeypatch.setattr(gateway_main, "publish_run_command", fake_publish_run_command)

    resp = client.post(
        "/run/announcements?force_send=true&email_recipients_override=qa@example.com",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 202
    assert captured["agent_name"] == "announcements"
    assert captured["force_send"] is True
    assert captured["email_recipients_override"] == "qa@example.com"
