from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import admin_reports as admin_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class SequencedSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No fake result prepared")
        return self._results.pop(0)


def test_admin_reports_requires_api_key() -> None:
    resp = client.get("/admin/reports")
    assert resp.status_code == 401


def test_admin_reports_page_renders(monkeypatch) -> None:
    run_row = SimpleNamespace(
        run_id=uuid4(),
        status="partial",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        metrics={"degraded": True},
    )
    report_row = SimpleNamespace(
        report_id=uuid4(),
        report_type="daily",
        period_key=date(2026, 3, 1),
        generated_at=datetime.now(timezone.utc),
        status="sent",
        subject="Daily Analyst",
        degraded=False,
        email_sent_at=datetime.now(timezone.utc),
    )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult([run_row]), FakeResult([report_row])])

    monkeypatch.setattr(admin_router, "get_session", fake_get_session)

    resp = client.get("/admin/reports", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert "Analyst Reports Admin" in resp.text
    assert "Latest Agent D Run" in resp.text


def test_admin_reports_trigger_and_resend(monkeypatch) -> None:
    run_id = str(uuid4())
    captured = {}

    async def fake_start_run(_agent_name: str):
        return run_id

    def fake_send_task(task_name: str, kwargs: dict):
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs

    monkeypatch.setattr(admin_router, "start_run", fake_start_run)
    monkeypatch.setattr(admin_router.celery_app, "send_task", fake_send_task)

    resp = client.post(
        "/admin/reports/trigger?report_type=weekly&period_key=2026-03-02",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert captured["task_name"] == "agent_analyst.run"
    assert captured["kwargs"]["report_type"] == "weekly"

    resp = client.post(
        "/admin/reports/resend?report_type=daily&period_key=2026-03-01&force=true",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert captured["kwargs"]["force_send"] is True
