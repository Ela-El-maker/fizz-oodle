from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import runs as runs_router


client = TestClient(app)


class FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return FakeScalarResult(self._rows)


def test_get_runs_returns_canonical_envelope(monkeypatch) -> None:
    row = SimpleNamespace(
        run_id=uuid4(),
        agent_name="system",
        status="success",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        metrics={"ping": True},
        error_message=None,
    )

    @asynccontextmanager
    async def fake_get_session():
        yield FakeSession([row])

    monkeypatch.setattr(runs_router, "get_session", fake_get_session)

    resp = client.get("/runs")
    assert resp.status_code == 200
    payload = resp.json()
    assert "items" in payload
    assert len(payload["items"]) == 1
    assert payload["items"][0]["agent_name"] == "system"
    assert payload["items"][0]["status"] == "success"


def test_post_run_requires_api_key() -> None:
    resp = client.post("/run/system")
    assert resp.status_code == 401


def test_get_runs_rejects_invalid_status() -> None:
    resp = client.get("/runs?status=invalid")
    assert resp.status_code == 400


def test_post_run_invalid_agent(monkeypatch) -> None:
    resp = client.post("/run/not-real", headers={"x-api-key": "change-me"})
    assert resp.status_code == 404


def test_post_run_enqueues_task(monkeypatch) -> None:
    run_id = str(uuid4())
    captured = {}

    async def fake_start_run(agent_name: str):
        assert agent_name == "system"
        return run_id

    def fake_send_task(task_name: str, kwargs: dict):
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs

    monkeypatch.setattr(runs_router, "start_run", fake_start_run)
    monkeypatch.setattr(runs_router.celery_app, "send_task", fake_send_task)

    resp = client.post("/run/system", headers={"x-api-key": "change-me"})
    assert resp.status_code == 202

    payload = resp.json()
    assert payload["run_id"] == run_id
    assert payload["status"] == "running"
    assert captured["task_name"] == "agent_system.ping"
    assert captured["kwargs"] == {"run_id": run_id}


def test_post_run_analyst_enqueues_task(monkeypatch) -> None:
    run_id = str(uuid4())
    captured = {}

    async def fake_start_run(agent_name: str):
        assert agent_name == "analyst"
        return run_id

    def fake_send_task(task_name: str, kwargs: dict):
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs

    monkeypatch.setattr(runs_router, "start_run", fake_start_run)
    monkeypatch.setattr(runs_router.celery_app, "send_task", fake_send_task)

    resp = client.post("/run/analyst", headers={"x-api-key": "change-me"})
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["run_id"] == run_id
    assert payload["agent_name"] == "analyst"
    assert captured["task_name"] == "agent_analyst.run"
    assert captured["kwargs"] == {"run_id": run_id}
