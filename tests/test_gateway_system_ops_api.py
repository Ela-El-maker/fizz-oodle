from __future__ import annotations

from fastapi.testclient import TestClient

from services.gateway import main as gateway_main
from services.gateway.main import app

client = TestClient(app)


def test_system_autonomy_state_requires_api_key() -> None:
    resp = client.get("/system/autonomy/state")
    assert resp.status_code == 401


def test_universe_summary_proxies_to_agent_a(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"tracked_companies": 69, "nse_tickers": 64}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/universe/summary", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["nse_tickers"] == 64
    assert captured["base"] == gateway_main.settings.AGENT_A_SERVICE_URL
    assert captured["path"] == "/universe/summary"


def test_system_autonomy_state_proxies_to_run_ledger(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"safe_mode": False}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/system/autonomy/state?refresh=true", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["item"]["safe_mode"] is False
    assert captured["base"] == "http://run-ledger-service:8011"
    assert captured["path"] == "/system/autonomy/state"
    assert captured["params"]["refresh"] is True


def test_system_healing_incidents_proxies_to_run_ledger(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"items": [{"incident_id": "1"}], "limit": 20}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/system/healing/incidents?limit=20", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["limit"] == 20
    assert captured["base"] == "http://run-ledger-service:8011"
    assert captured["path"] == "/system/healing/incidents"
    assert captured["params"]["limit"] == 20


def test_system_learning_summary_proxies_to_run_ledger(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"summary_id": "abc"}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/system/learning/summary", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["item"]["summary_id"] == "abc"
    assert captured["base"] == "http://run-ledger-service:8011"
    assert captured["path"] == "/system/learning/summary"


def test_system_self_mod_state_proxies_to_run_ledger(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"item": {"pending_count": 1}}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/system/self-mod/state", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["item"]["pending_count"] == 1
    assert captured["path"] == "/system/self-mod/state"


def test_system_self_mod_proposals_proxies_to_run_ledger(monkeypatch) -> None:
    captured: dict = {}

    async def fake_forward_get(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"items": [], "limit": 5}

    monkeypatch.setattr(gateway_main, "_forward_get", fake_forward_get)
    resp = client.get("/system/self-mod/proposals?limit=5", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["limit"] == 5
    assert captured["path"] == "/system/self-mod/proposals"
    assert captured["params"]["limit"] == 5


def test_system_self_mod_generate_uses_internal_post(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"created": 1, "applied": 1}

    monkeypatch.setattr(gateway_main, "_forward_post", fake_post)
    resp = client.post("/system/self-mod/generate?refresh=true&auto_apply=true", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["created"] == 1
    assert captured["path"] == "/system/self-mod/generate"
    assert captured["params"]["auto_apply"] is True


def test_system_self_mod_apply_uses_internal_post(monkeypatch) -> None:
    captured: dict = {}

    async def fake_post(base: str, path: str, *, params: dict | None = None):
        captured["base"] = base
        captured["path"] = path
        captured["params"] = params
        return {"proposal": {"status": "applied"}}

    monkeypatch.setattr(gateway_main, "_forward_post", fake_post)
    resp = client.post("/system/self-mod/apply/abc?auto_applied=true", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["proposal"]["status"] == "applied"
    assert captured["path"] == "/system/self-mod/apply/abc"
    assert captured["params"]["auto_applied"] is True


def test_insights_overview_latest_returns_compact_payload(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, params: dict | None = None, headers: dict | None = None):
            if url.endswith("/briefings/latest"):
                return FakeResponse(
                    {
                        "item": {
                            "status": "sent",
                            "generated_at": "2026-03-05T04:00:00+00:00",
                            "briefing_date": "2026-03-05",
                            "subject": "Daily",
                            "html_content": "<html/>",
                            "human_summary_v2": {"headline": "Briefing headline"},
                            "metrics": {"human_summary_v2": {"quality": {"coverage_pct": 90}}},
                        }
                    }
                )
            if url.endswith("/announcements/stats"):
                return FakeResponse(
                    {
                        "total": 12,
                        "alerted": 10,
                        "human_summary_v2": {"headline": "Announcement headline"},
                    }
                )
            if url.endswith("/sentiment/digest/latest"):
                return FakeResponse({"item": {"status": "sent", "week_start": "2026-03-02", "html_content": "<html/>"}})
            if url.endswith("/reports/latest") and params == {"type": "daily"}:
                return FakeResponse({"item": {"status": "sent", "generated_at": "2026-03-05T07:00:00+00:00", "html_content": "<html/>"}})
            if url.endswith("/reports/latest") and params == {"type": "weekly"}:
                return FakeResponse({"item": {"status": "sent", "generated_at": "2026-03-02T07:00:00+00:00", "html_content": "<html/>"}})
            if url.endswith("/archive/latest"):
                return FakeResponse(
                    {
                        "run_type": "weekly",
                        "period_key": "2026-03-02",
                        "status": "sent",
                        "human_summary_v2": {"headline": "Archive headline"},
                        "summary": {"metrics": {"human_summary_v2": {"quality": {"confidence_score": 80}}}},
                    }
                )
            return FakeResponse({}, status_code=404)

    monkeypatch.setattr(gateway_main.httpx, "AsyncClient", FakeAsyncClient)
    resp = client.get("/insights/overview/latest", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    data = resp.json()["overview"]
    assert data["briefing"]["human_summary_v2"]["headline"] == "Briefing headline"
    assert "html_content" not in data["briefing"]
    assert data["announcements"]["human_summary_v2"]["headline"] == "Announcement headline"
    assert "html_content" not in data["analyst_daily"]
    assert "html_content" not in data["analyst_weekly"]
    assert data["archive_weekly"]["human_summary_v2"]["headline"] == "Archive headline"


def test_insights_quality_latest_returns_compact_analysis(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict, status_code: int = 200):
            self._payload = payload
            self.status_code = status_code

        def json(self) -> dict:
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url: str, params: dict | None = None, headers: dict | None = None):
            if url.endswith("/sources/health"):
                return FakeResponse({"items": [{"source_id": "nse_official"}]})
            if url.endswith("/sentiment/sources/health"):
                return FakeResponse({"items": [{"source_id": "google_news_ke_markets"}]})
            if url.endswith("/briefing/sources/health"):
                return FakeResponse({"items": [{"source_id": "mystocks"}]})
            if url.endswith("/reports/latest?type=daily"):
                return FakeResponse(
                    {
                        "item": {
                            "status": "sent",
                            "generated_at": "2026-03-05T07:00:00+00:00",
                            "period_key": "2026-03-05",
                            "degraded": False,
                            "human_summary_v2": {"headline": "Analyst headline"},
                            "metrics": {
                                "feedback_applied": True,
                                "feedback_coverage_pct": 88.5,
                                "status_reason": "upstream_quality_ok",
                            },
                            "html_content": "<html/>",
                            "json_payload": {"hidden": True},
                        }
                    }
                )
            if url.endswith("/archive/latest?run_type=weekly"):
                return FakeResponse(
                    {
                        "run_type": "weekly",
                        "period_key": "2026-03-02",
                        "status": "sent",
                        "created_at": "2026-03-05T08:00:00+00:00",
                        "human_summary_v2": {"headline": "Archive headline"},
                        "summary": {
                            "metrics": {
                                "upstream_quality_score": 96,
                                "degraded": False,
                                "warnings": ["none"],
                            }
                        },
                    }
                )
            return FakeResponse({}, status_code=404)

    monkeypatch.setattr(gateway_main.httpx, "AsyncClient", FakeAsyncClient)
    resp = client.get("/insights/quality/latest", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    analysis = resp.json()["analysis_quality"]
    assert analysis["analyst_latest"]["feedback_applied"] is True
    assert analysis["analyst_latest"]["feedback_coverage_pct"] == 88.5
    assert "html_content" not in analysis["analyst_latest"]
    assert "json_payload" not in analysis["analyst_latest"]
    assert analysis["archivist_latest"]["upstream_quality_score"] == 96
