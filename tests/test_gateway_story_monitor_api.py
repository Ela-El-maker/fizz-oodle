from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_gateway_story_monitor_status_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"agent_status": "ACTIVE"}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/stories/monitor/status?window_minutes=30", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["agent_status"] == "ACTIVE"
    assert captured["base"] == gateway_main.settings.AGENT_F_SERVICE_URL
    assert captured["path"] == "/stories/monitor/status"
    assert captured["params"]["window_minutes"] == 30


def test_gateway_story_monitor_snapshot_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_fetch_monitor_snapshot(*, window_minutes: int = 30, events_limit: int = 20, cycles_limit: int = 5):
        captured["window_minutes"] = window_minutes
        captured["events_limit"] = events_limit
        captured["cycles_limit"] = cycles_limit
        return {"generated_at": "2026-03-05T00:00:00+00:00"}

    monkeypatch.setattr(gateway_main, "_fetch_monitor_snapshot", fake_fetch_monitor_snapshot)
    resp = client.get(
        "/stories/monitor/snapshot?window_minutes=60&events_limit=10&cycles_limit=3",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["generated_at"] == "2026-03-05T00:00:00+00:00"
    assert captured["window_minutes"] == 60
    assert captured["events_limit"] == 10
    assert captured["cycles_limit"] == 3


def test_gateway_story_monitor_ws(monkeypatch) -> None:
    async def fake_fetch_monitor_snapshot(*, window_minutes: int = 30, events_limit: int = 20, cycles_limit: int = 5):
        return {
            "generated_at": "2026-03-05T00:00:00+00:00",
            "status": {
                "agent_status": "ACTIVE",
                "current_task": "Idle",
                "progress_pct": 100,
                "progress_label": "Narrative Generation Progress",
                "started_at": None,
                "estimated_completion_at": None,
                "last_cycle_id": None,
                "status_reason": None,
            },
            "pipeline": {"window_minutes": 30, "nodes": [], "links": []},
            "requests": {"items": [], "limit": 20},
            "scrapers": {"items": []},
            "events": {"items": [], "limit": 20},
            "cycles": {"items": [], "limit": 5},
            "health": {
                "data_freshness": {"status": "ok", "minutes_since_last_success": 1},
                "agent_connectivity": {"status": "ok", "healthy_agents": 6, "total_agents": 6},
                "pipeline_latency": {"status": "ok", "p50_seconds": 1.2, "p95_seconds": 1.5},
                "scraper_health": {"status": "ok", "active_jobs": 0, "recent_failures": 0},
            },
        }

    monkeypatch.setattr(gateway_main, "_fetch_monitor_snapshot", fake_fetch_monitor_snapshot)

    with client.websocket_connect("/stories/monitor/ws?api_key=change-me") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "snapshot"
        assert frame["data"]["status"]["agent_status"] == "ACTIVE"
