from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import health as health_router


client = TestClient(app)


def test_health_ok(monkeypatch) -> None:
    async def fake_db():
        return {"status": "ok"}

    async def fake_redis():
        return {"status": "ok"}

    async def fake_runs():
        return {"system": {"status": "never_run", "run_id": None, "started_at": None, "finished_at": None}}

    monkeypatch.setattr(health_router, "_check_db", fake_db)
    monkeypatch.setattr(health_router, "_check_redis", fake_redis)
    monkeypatch.setattr(health_router, "_last_runs", fake_runs)

    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["api"]["status"] == "ok"
    assert "postgres" in payload["dependencies"]
    assert "redis" in payload["dependencies"]
    assert "ollama" in payload["dependencies"]
    assert "agents" in payload
    assert "agent_d" in payload["agents"]


def test_health_degraded_when_one_dependency_fails(monkeypatch) -> None:
    async def fake_db():
        return {"status": "fail", "error": "db down"}

    async def fake_redis():
        return {"status": "ok"}

    async def fake_runs():
        return {}

    monkeypatch.setattr(health_router, "_check_db", fake_db)
    monkeypatch.setattr(health_router, "_check_redis", fake_redis)
    monkeypatch.setattr(health_router, "_last_runs", fake_runs)

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"


def test_health_fail_when_all_dependencies_fail(monkeypatch) -> None:
    async def fake_db():
        return {"status": "fail", "error": "db down"}

    async def fake_redis():
        return {"status": "fail", "error": "redis down"}

    async def fake_runs():
        return {}

    monkeypatch.setattr(health_router, "_check_db", fake_db)
    monkeypatch.setattr(health_router, "_check_redis", fake_redis)
    monkeypatch.setattr(health_router, "_last_runs", fake_runs)

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "fail"
