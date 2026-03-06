from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import announcements as announcements_router

client = TestClient(app)


class FakeResult:
    def __init__(self, scalar_one=None, scalars_all=None, all_rows=None, scalar_one_or_none=None):
        self._scalar_one = scalar_one
        self._scalars_all = scalars_all or []
        self._all_rows = all_rows or []
        self._scalar_one_or_none = scalar_one_or_none
        self._mode = "rows"

    def scalar_one(self):
        return self._scalar_one

    def scalar_one_or_none(self):
        return self._scalar_one_or_none

    def scalars(self):
        self._mode = "scalars"
        return self

    def all(self):
        if self._mode == "scalars":
            return self._scalars_all
        return self._all_rows


class SequencedSession:
    def __init__(self, results):
        self._results = list(results)
        self.commits = 0

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No fake result prepared for execute call")
        return self._results.pop(0)

    async def commit(self):
        self.commits += 1


def test_get_announcements_with_filters(monkeypatch) -> None:
    row = SimpleNamespace(
        announcement_id="abc",
        source_id="nse_official",
        ticker="SCOM",
        company_name="Safaricom",
        headline="Safaricom dividend declared",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        announcement_date=datetime.now(timezone.utc),
        announcement_type="dividend",
        type_confidence=0.91,
        details="Details",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        alerted=False,
        alerted_at=None,
    )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([
            FakeResult(scalar_one=1),
            FakeResult(scalars_all=[row]),
        ])

    monkeypatch.setattr(announcements_router, "get_session", fake_get_session)
    resp = client.get("/announcements?ticker=SCOM&type=dividend&limit=10", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["ticker"] == "SCOM"
    assert "severity" in payload["items"][0]
    assert "severity_score" in payload["items"][0]


def test_get_announcement_by_id(monkeypatch) -> None:
    row = SimpleNamespace(
        announcement_id="abc",
        source_id="nse_official",
        ticker="SCOM",
        company_name="Safaricom",
        headline="Safaricom dividend declared",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        announcement_date=datetime.now(timezone.utc),
        announcement_type="dividend",
        type_confidence=0.91,
        details="Details",
        content_hash="h",
        raw_payload={"x": 1},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        alerted=False,
        alerted_at=None,
        classifier_version="rule-v1",
        normalizer_version="n-v1",
    )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalar_one_or_none=row)])

    monkeypatch.setattr(announcements_router, "get_session", fake_get_session)
    resp = client.get("/announcements/abc", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["announcement_id"] == "abc"
    assert "severity" in resp.json()
    assert "severity_score" in resp.json()


def test_source_health_endpoint(monkeypatch) -> None:
    row = SimpleNamespace(
        source_id="nse_official",
        last_success_at=datetime.now(timezone.utc),
        last_failure_at=None,
        consecutive_failures=0,
        breaker_state="closed",
        cooldown_until=None,
        last_metrics={"items_found": 3},
    )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalars_all=[row])])

    monkeypatch.setattr(announcements_router, "get_session", fake_get_session)
    resp = client.get("/sources/health", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    row = next(item for item in resp.json()["items"] if item["source_id"] == "nse_official")
    assert row["tier"] in {"core", "secondary"}
    assert "required_for_success" in row
    assert "last_error_type" in row


def test_announcements_stats_includes_human_summary(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession(
            [
                FakeResult(scalar_one=12),  # total
                FakeResult(scalar_one=8),   # alerted
                FakeResult(scalar_one=4),   # unalerted
                FakeResult(all_rows=[("dividend", 5), ("earnings", 3), ("profit_warning", 1)]),  # by_type
                FakeResult(all_rows=[("nse_official", 7), ("company_ir_pages", 5)]),  # by_source
                FakeResult(all_rows=[("dividend", 5), ("earnings_cycle", 3)]),  # by_theme
                FakeResult(all_rows=[("oil", 2)]),  # high_impact_global_by_theme
                FakeResult(scalar_one=0),  # high_impact_global_total
            ]
        )

    monkeypatch.setattr(announcements_router, "get_session", fake_get_session)
    resp = client.get("/announcements/stats", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 12
    assert body["alerted"] == 8
    assert body["unalerted"] == 4
    assert "global_outside_total" in body
    assert "high_impact_global_total" in body
    assert "human_summary" in body
    assert isinstance(body["human_summary"].get("headline"), str)


def test_get_announcement_insight(monkeypatch) -> None:
    row = SimpleNamespace(
        announcement_id="abc",
        source_id="nse_official",
        ticker="SCOM",
        company_name="Safaricom",
        headline="Safaricom dividend declared",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        announcement_date=datetime.now(timezone.utc),
        announcement_type="dividend",
        type_confidence=0.91,
        details="Details",
        content_hash="h",
        raw_payload={},
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        alerted=False,
        alerted_at=None,
        classifier_version="rule-v1",
        normalizer_version="n-v1",
    )

    async def fake_get_or_build(row, *, refresh_context_if_needed, force_regenerate, now_utc):
        assert row.announcement_id == "abc"
        assert refresh_context_if_needed is True
        assert force_regenerate is False
        return (
            {
                "version": "v1",
                "generated_at": now_utc.isoformat(),
                "insight": {"what_happened": "x"},
                "quality": {"llm_used": False, "fallback_used": True},
                "research_links": [],
            },
            {"cache_hit": False},
        )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalar_one_or_none=row)])

    monkeypatch.setattr(announcements_router, "get_session", fake_get_session)
    monkeypatch.setattr(announcements_router, "get_or_build_announcement_insight", fake_get_or_build)

    resp = client.get("/announcements/abc/insight", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["announcement_id"] == "abc"
    assert body["item"]["version"] == "v1"
    assert body["meta"]["cache_hit"] is False


def test_post_announcement_context_refresh(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        announcement_id="abc",
        source_id="nse_official",
        ticker="SCOM",
        company_name="Safaricom",
        headline="Safaricom dividend declared",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        announcement_date=now,
        announcement_type="dividend",
        type_confidence=0.91,
        details="Details",
        content_hash="h",
        raw_payload={},
        first_seen_at=now,
        last_seen_at=now,
        alerted=False,
        alerted_at=None,
        classifier_version="rule-v1",
        normalizer_version="n-v1",
    )

    async def fake_refresh_context(row, now_utc):
        row.details = "Updated details"
        row.last_seen_at = now_utc
        return {"refreshed": True, "updated": True, "reason": "ok"}

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalar_one_or_none=row)])

    monkeypatch.setattr(announcements_router, "get_session", fake_get_session)
    monkeypatch.setattr(announcements_router, "refresh_announcement_context", fake_refresh_context)

    resp = client.post("/announcements/abc/context/refresh", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["announcement_id"] == "abc"
    assert body["refresh"]["refreshed"] is True
    assert body["details_length"] > 0
