from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import patterns as patterns_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class SequencedSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No fake result prepared")
        return self._results.pop(0)


def test_archive_latest_requires_api_key() -> None:
    resp = client.get("/archive/latest")
    assert resp.status_code == 401


def test_patterns_summary_and_archive_latest(monkeypatch) -> None:
    pattern = SimpleNamespace(
        pattern_id=uuid4(),
        ticker="SCOM",
        pattern_type="sentiment_shift",
        description="desc",
        status="confirmed",
        confidence_pct=85.0,
        accuracy_pct=72.0,
        occurrence_count=9,
        avg_impact_1d=0.5,
        avg_impact_5d=1.0,
        active=True,
        updated_at=datetime.now(timezone.utc),
    )
    archive = SimpleNamespace(
        run_type="weekly",
        period_key=date(2026, 3, 2),
        status="sent",
        summary={"metrics": {"degraded": False}},
        created_at=datetime.now(timezone.utc),
    )

    @asynccontextmanager
    async def fake_get_session_summary():
        yield SequencedSession([FakeResult(rows=[pattern])])

    monkeypatch.setattr(patterns_router, "get_session", fake_get_session_summary)
    summary = client.get("/patterns/summary", headers={"x-api-key": "change-me"})
    assert summary.status_code == 200
    assert summary.json()["confirmed"] == 1

    @asynccontextmanager
    async def fake_get_session_latest():
        yield SequencedSession([FakeResult(scalar=archive)])

    monkeypatch.setattr(patterns_router, "get_session", fake_get_session_latest)

    latest = client.get("/archive/latest?run_type=weekly", headers={"x-api-key": "change-me"})
    assert latest.status_code == 200
    assert latest.json()["run_type"] == "weekly"


def test_impacts_404_when_missing(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalar=None)])

    monkeypatch.setattr(patterns_router, "get_session", fake_get_session)

    resp = client.get("/impacts/other", headers={"x-api-key": "change-me"})
    assert resp.status_code == 404


def test_archive_latest_404_when_missing(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalar=None)])

    monkeypatch.setattr(patterns_router, "get_session", fake_get_session)
    resp = client.get("/archive/latest?run_type=monthly", headers={"x-api-key": "change-me"})
    assert resp.status_code == 404
