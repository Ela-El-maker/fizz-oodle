from __future__ import annotations

import pytest

from services.gateway import email_validation as ev


@pytest.mark.asyncio
async def test_email_validation_daily_sequence_success(monkeypatch) -> None:
    monkeypatch.setattr(ev.settings, "EMAIL_VALIDATION_ENABLED", True)
    monkeypatch.setattr(ev.settings, "EMAIL_VALIDATION_RECIPIENTS", "qa@example.com")

    dispatched: list[str] = []
    step_upserts: list[dict] = []
    finished: dict = {}

    async def fake_internal_post(path: str, params: dict | None = None, json_body: dict | None = None):
        if path == "/internal/email-validation/start":
            return {
                "validation_run_id": "11111111-1111-1111-1111-111111111111",
                "window": "daily",
                "period_key": "2026-03-02",
                "status": "running",
                "summary_json": {},
                "reused": False,
            }
        if path.endswith("/step"):
            step_upserts.append(json_body or {})
            return {"accepted": True}
        if path.endswith("/finish"):
            finished.update(json_body or {})
            return {"accepted": True}
        raise AssertionError(f"unexpected path: {path}")

    async def fake_publish_run_command(**kwargs):
        dispatched.append(kwargs["agent_name"])
        return {"command_id": f"cmd-{kwargs['agent_name']}"}

    async def fake_wait(run_id: str, agent_name: str):  # noqa: ARG001
        return {
            "status": "success",
            "metrics": {"email_sent": True, "email_error": None},
            "error_message": None,
        }

    monkeypatch.setattr(ev, "_run_ledger_internal_post", fake_internal_post)
    monkeypatch.setattr(ev, "publish_run_command", fake_publish_run_command)
    monkeypatch.setattr(ev, "_wait_for_terminal_run", fake_wait)

    result = await ev.run_email_validation("daily", force=True)
    assert result["status"] == "success"
    assert dispatched == ["briefing", "announcements", "analyst"]
    assert len(step_upserts) == 3
    assert finished["status"] == "success"


@pytest.mark.asyncio
async def test_email_validation_weekly_fails_when_sentiment_not_sent(monkeypatch) -> None:
    monkeypatch.setattr(ev.settings, "EMAIL_VALIDATION_ENABLED", True)
    monkeypatch.setattr(ev.settings, "EMAIL_VALIDATION_RECIPIENTS", "qa@example.com")

    async def fake_internal_post(path: str, params: dict | None = None, json_body: dict | None = None):  # noqa: ARG001
        if path == "/internal/email-validation/start":
            return {
                "validation_run_id": "22222222-2222-2222-2222-222222222222",
                "window": "weekly",
                "period_key": "2026-03-02",
                "status": "running",
                "summary_json": {},
                "reused": False,
            }
        return {"accepted": True}

    async def fake_publish_run_command(**kwargs):  # noqa: ARG001
        return {"command_id": "cmd"}

    async def fake_wait(run_id: str, agent_name: str):  # noqa: ARG001
        if agent_name == "sentiment":
            return {"status": "success", "metrics": {"digest_sent": False, "digest_error": None}, "error_message": None}
        return {"status": "success", "metrics": {"email_sent": True, "email_error": None}, "error_message": None}

    monkeypatch.setattr(ev, "_run_ledger_internal_post", fake_internal_post)
    monkeypatch.setattr(ev, "publish_run_command", fake_publish_run_command)
    monkeypatch.setattr(ev, "_wait_for_terminal_run", fake_wait)

    result = await ev.run_email_validation("weekly", force=True)
    assert result["status"] == "fail"
    assert result["summary"]["all_passed"] is False


@pytest.mark.asyncio
async def test_email_validation_returns_reused_when_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(ev.settings, "EMAIL_VALIDATION_ENABLED", True)
    monkeypatch.setattr(ev.settings, "EMAIL_VALIDATION_RECIPIENTS", "qa@example.com")

    async def fake_internal_post(path: str, params: dict | None = None, json_body: dict | None = None):  # noqa: ARG001
        assert path == "/internal/email-validation/start"
        return {
            "validation_run_id": "33333333-3333-3333-3333-333333333333",
            "window": "daily",
            "period_key": "2026-03-02",
            "status": "success",
            "summary_json": {"all_passed": True},
            "reused": True,
        }

    monkeypatch.setattr(ev, "_run_ledger_internal_post", fake_internal_post)

    result = await ev.run_email_validation("daily", force=False)
    assert result["reused"] is True
    assert result["status"] == "success"

