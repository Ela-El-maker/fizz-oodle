from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_gateway_scheduler_monitor_status_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"status": {"scheduler_status": "ok"}, "metrics": {}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/scheduler/monitor/status", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["status"]["scheduler_status"] == "ok"
    assert captured["base"] == "http://run-ledger-service:8011"
    assert captured["path"] == "/scheduler/monitor/status"


def test_gateway_scheduler_monitor_snapshot_proxy(monkeypatch) -> None:
    captured: dict = {}

    async def fake_fetch_scheduler_snapshot(*, hours: int = 24, events_limit: int = 50, failed_agent: str | None = None):
        captured["hours"] = hours
        captured["events_limit"] = events_limit
        captured["failed_agent"] = failed_agent
        return {"generated_at": "2026-03-06T00:00:00+00:00", "status": {}, "metrics": {}}

    monkeypatch.setattr(gateway_main, "_fetch_scheduler_snapshot", fake_fetch_scheduler_snapshot)
    resp = client.get(
        "/scheduler/monitor/snapshot?hours=12&events_limit=30&failed_agent=announcements",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["generated_at"] == "2026-03-06T00:00:00+00:00"
    assert captured["hours"] == 12
    assert captured["events_limit"] == 30
    assert captured["failed_agent"] == "announcements"


def test_gateway_scheduler_control_dispatch(monkeypatch) -> None:
    captured: dict = {}

    async def fake_call_internal_post(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"accepted": True}

    monkeypatch.setattr(gateway_main, "_call_internal_post", fake_call_internal_post)
    resp = client.post("/scheduler/control/dispatch/agent_f_narrator_30m", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert captured["base"] == "http://scheduler-service:8010"
    assert captured["path"] == "/internal/dispatch/agent_f_narrator_30m"


def test_gateway_scheduler_monitor_ws(monkeypatch) -> None:
    async def fake_fetch_scheduler_snapshot(*, hours: int = 24, events_limit: int = 50, failed_agent: str | None = None):
        return {
            "generated_at": "2026-03-06T00:00:00+00:00",
            "time": {"now_utc": "2026-03-06T00:00:00+00:00", "now_eat": "2026-03-06T03:00:00+03:00"},
            "status": {
                "scheduler_status": "ok",
                "last_tick_at": None,
                "last_tick_at_eat": None,
                "loop_interval_seconds": 10,
                "schedules_loaded": 1,
            },
            "metrics": {
                "active_runs": 1,
                "queued_jobs": 0,
                "blocked_jobs": 0,
                "next_run_eta_seconds": 30,
                "next_email_eta_seconds": 60,
                "llm_active_jobs": 1,
            },
            "past": {"items": [], "limit": 50},
            "present": {"running": [], "queued": [], "blocked": []},
            "future": {"hours": 24, "items": []},
            "pipeline": {"window_minutes": 120, "nodes": [], "links": []},
            "heatmap": {"hours": 24, "buckets": [], "rows": []},
            "email": {
                "next_scheduled_at_utc": None,
                "next_scheduled_at_eat": None,
                "latest_validation_window": None,
                "latest_validation_status": None,
                "latest_validation_at": None,
                "sent_count_recent": 0,
                "failure_count_recent": 0,
            },
            "events": {"items": [], "limit": 50},
            "impact": {"failed_agent": None, "items": []},
            "health": {
                "data_freshness": {"status": "ok", "minutes_since_last_success": 5},
                "agent_connectivity": {"status": "ok", "healthy_agents": 6, "total_agents": 6},
                "pipeline_latency": {"status": "ok", "p50_seconds": 1.0, "p95_seconds": 1.5},
                "scheduler_dispatch": {"status": "ok", "accepted": 1, "failed": 0, "skipped": 0},
                "email_dispatch": {"status": "ok", "sent_count": 0, "recent_failures": 0},
            },
        }

    monkeypatch.setattr(gateway_main, "_fetch_scheduler_snapshot", fake_fetch_scheduler_snapshot)

    with client.websocket_connect("/scheduler/monitor/ws?api_key=change-me") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "snapshot"
        assert frame["data"]["status"]["scheduler_status"] == "ok"
