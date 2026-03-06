from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import reports as reports_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar

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


def _row() -> SimpleNamespace:
    return SimpleNamespace(
        report_id=uuid4(),
        report_type="daily",
        period_key=date(2026, 3, 1),
        generated_at=datetime.now(timezone.utc),
        status="sent",
        subject="Daily report",
        html_content="<p>ok</p>",
        json_payload={"overview": ["x"]},
        inputs_summary={"briefing": {"available": True}},
        metrics={"degraded": False},
        email_sent_at=datetime.now(timezone.utc),
        email_error=None,
        payload_hash="abc",
        llm_used=False,
        degraded=False,
    )


def test_reports_requires_api_key() -> None:
    resp = client.get("/reports/latest")
    assert resp.status_code == 401


def test_reports_latest_and_get(monkeypatch) -> None:
    row = _row()

    @asynccontextmanager
    async def fake_get_session_latest():
        yield SequencedSession([FakeResult([row])])

    monkeypatch.setattr(reports_router, "get_session", fake_get_session_latest)

    latest = client.get("/reports/latest?type=daily", headers={"x-api-key": "change-me"})
    assert latest.status_code == 200
    payload = latest.json()["item"]
    assert payload["report_type"] == "daily"

    @asynccontextmanager
    async def fake_get_session_get():
        yield SequencedSession([FakeResult([row]), FakeResult([row])])

    monkeypatch.setattr(reports_router, "get_session", fake_get_session_get)

    got = client.get(f"/reports/{row.report_id}", headers={"x-api-key": "change-me"})
    assert got.status_code == 200
    assert got.json()["item"]["report_id"] == str(row.report_id)

    inputs = client.get(f"/reports/{row.report_id}/inputs", headers={"x-api-key": "change-me"})
    assert inputs.status_code == 200
    assert inputs.json()["inputs_summary"]["briefing"]["available"] is True


def test_reports_list(monkeypatch) -> None:
    row = _row()

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult(scalar=1), FakeResult([row])])

    monkeypatch.setattr(reports_router, "get_session", fake_get_session)

    resp = client.get("/reports?type=daily&limit=10&offset=0", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["total"] == 1
    assert payload["items"][0]["subject"] == "Daily report"
