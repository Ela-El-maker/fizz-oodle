from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import admin as admin_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class SequencedSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No fake result prepared for execute call")
        return self._results.pop(0)


def test_admin_announcements_page_renders(monkeypatch) -> None:
    ann_row = SimpleNamespace(
        announcement_id="abc123",
        ticker="SCOM",
        announcement_type="dividend",
        headline="Safaricom declares dividend",
        url="https://example.com/a",
        source_id="nse_official",
        alerted=False,
        announcement_date=datetime.now(timezone.utc),
    )
    run_row = SimpleNamespace(
        run_id=uuid4(),
        status="partial",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        metrics={"sources": {"nse_official": {"items_found": 3}}},
    )
    source_health_row = SimpleNamespace(
        source_id="nse_official",
        breaker_state="closed",
        consecutive_failures=0,
        cooldown_until=None,
        last_metrics={"items_found": 3},
    )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession(
            [
                FakeResult([ann_row]),
                FakeResult([run_row]),
                FakeResult([source_health_row]),
            ]
        )

    monkeypatch.setattr(admin_router, "get_session", fake_get_session)
    resp = client.get(
        "/admin/announcements?ticker=SCOM&type=dividend&source_id=nse_official&date_from=2026-03-01&date_to=2026-03-02&alerted=false",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert "Announcements Admin" in resp.text
    assert "Source Health" in resp.text
    assert "Latest Agent B Run" in resp.text


def test_admin_trigger_announcements(monkeypatch) -> None:
    run_id = str(uuid4())
    captured = {}

    async def fake_start_run(_agent_name: str):
        return run_id

    def fake_send_task(task_name: str, kwargs: dict):
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs

    monkeypatch.setattr(admin_router, "start_run", fake_start_run)
    monkeypatch.setattr(admin_router.celery_app, "send_task", fake_send_task)

    resp = client.post("/admin/announcements/trigger", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["run_id"] == run_id
    assert captured["task_name"] == "agent_announcements.run"
    assert captured["kwargs"] == {"run_id": run_id}

