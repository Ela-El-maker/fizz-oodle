from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import pytest

from apps.agents.archivist import pipeline as archivist_pipeline
from apps.core.models import ArchiveRun


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


@dataclass
class _FakeSession:
    queue: list[_Result]
    added: list[Any]

    async def execute(self, _stmt):
        if not self.queue:
            return _Result()
        return self.queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None


async def _fake_fetch_json(_client, url: str, params: dict | None = None) -> dict:
    if url.endswith("/reports"):
        return {
            "items": [
                {
                    "report_id": "rep-1",
                    "report_type": "daily",
                    "period_key": "2026-03-02",
                    "degraded": False,
                }
            ]
        }
    if url.endswith("/sentiment/weekly"):
        return {
            "items": [
                {
                    "week_start": "2026-03-02",
                    "ticker": "SCOM",
                    "mentions_count": 6,
                    "wow_delta": 0.20,
                    "confidence": 0.8,
                    "weighted_score": 0.25,
                }
            ]
        }
    if url.endswith("/announcements"):
        return {
            "items": [
                {
                    "ticker": "SCOM",
                    "announcement_type": "other",
                    "announcement_date": "2026-03-02T00:00:00+00:00",
                }
            ]
        }
    return {"items": []}


async def _fake_fetch_json_sentiment_error(_client, url: str, params: dict | None = None) -> dict:
    if url.endswith("/sentiment/weekly"):
        raise RuntimeError("upstream sentiment error")
    return await _fake_fetch_json(_client, url, params)


async def _none_impact(*_args, **_kwargs):
    return None


async def _noop_upsert_pattern(**_kwargs):
    return None


async def _noop_apply_lifecycle(_session):
    return 0


async def _noop_publish(payload: dict):
    return payload


def _send_ok(*, subject: str, html: str):
    assert subject
    assert html
    return True, None


@pytest.mark.asyncio
async def test_agent_e_weekly_happy_path_emits_event(monkeypatch) -> None:
    fake_session = _FakeSession(
        queue=[
            _Result(rows=[]),  # preload report rows
            _Result(rows=[]),  # preload sentiment rows
            _Result(rows=[]),  # preload announcements rows
            _Result(),  # outcome insert
            _Result(scalar=None),  # accuracy existing
            _Result(rows=[]),  # accuracy rows
            _Result(rows=[]),  # pattern rows
            _Result(rows=[]),  # impact rows
            _Result(scalar=None),  # archive existing
        ],
        added=[],
    )
    finished: dict[str, Any] = {}
    published: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_get_session():
        yield fake_session

    async def fake_start_run(_agent_name: str, run_id: str | None = None):
        return run_id or "11111111-1111-1111-1111-111111111111"

    async def fake_finish_run(run_id, status, **kwargs):
        finished["run_id"] = run_id
        finished["status"] = status
        finished["metrics"] = kwargs.get("metrics") or {}

    async def fake_publish(payload: dict):
        published["payload"] = payload
        return payload

    monkeypatch.setattr(archivist_pipeline, "get_session", fake_get_session)
    monkeypatch.setattr(archivist_pipeline, "start_run", fake_start_run)
    monkeypatch.setattr(archivist_pipeline, "finish_run", fake_finish_run)
    monkeypatch.setattr(archivist_pipeline, "_fetch_json", _fake_fetch_json)
    monkeypatch.setattr(archivist_pipeline, "_compute_announcement_impact", _none_impact)
    monkeypatch.setattr(archivist_pipeline, "_upsert_pattern", _noop_upsert_pattern)
    monkeypatch.setattr(archivist_pipeline, "_apply_pattern_lifecycle", _noop_apply_lifecycle)
    monkeypatch.setattr(archivist_pipeline, "publish_archivist_patterns_updated", fake_publish)
    monkeypatch.setattr(archivist_pipeline, "send_archive_email", _send_ok)

    result = await archivist_pipeline.run_archivist_pipeline(run_type="weekly", period_key=date(2026, 3, 2))
    assert result["status"] == "success"
    assert finished["status"] == "success"
    assert finished["metrics"]["email_sent"] is True
    assert "payload" in published
    assert any(isinstance(item, ArchiveRun) for item in fake_session.added)


@pytest.mark.asyncio
async def test_agent_e_monthly_partial_when_upstream_missing(monkeypatch) -> None:
    fake_session = _FakeSession(
        queue=[
            _Result(rows=[]),  # preload report rows
            _Result(rows=[]),  # preload sentiment rows
            _Result(rows=[]),  # preload announcements rows
            _Result(scalar=None),  # accuracy existing
            _Result(rows=[]),  # accuracy rows
            _Result(rows=[]),  # pattern rows
            _Result(rows=[]),  # impact rows
            _Result(scalar=None),  # archive existing
        ],
        added=[],
    )
    finished: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_get_session():
        yield fake_session

    async def fake_start_run(_agent_name: str, run_id: str | None = None):
        return run_id or "22222222-2222-2222-2222-222222222222"

    async def fake_finish_run(run_id, status, **kwargs):
        finished["run_id"] = run_id
        finished["status"] = status
        finished["metrics"] = kwargs.get("metrics") or {}

    async def fake_fetch(_client, url: str, params: dict | None = None):
        return {"items": []}

    monkeypatch.setattr(archivist_pipeline, "get_session", fake_get_session)
    monkeypatch.setattr(archivist_pipeline, "start_run", fake_start_run)
    monkeypatch.setattr(archivist_pipeline, "finish_run", fake_finish_run)
    monkeypatch.setattr(archivist_pipeline, "_fetch_json", fake_fetch)
    monkeypatch.setattr(archivist_pipeline, "_upsert_pattern", _noop_upsert_pattern)
    monkeypatch.setattr(archivist_pipeline, "_apply_pattern_lifecycle", _noop_apply_lifecycle)
    monkeypatch.setattr(archivist_pipeline, "publish_archivist_patterns_updated", _noop_publish)
    monkeypatch.setattr(archivist_pipeline, "send_archive_email", _send_ok)

    result = await archivist_pipeline.run_archivist_pipeline(run_type="monthly", period_key=date(2026, 3, 1))
    assert result["status"] == "partial"
    assert finished["status"] == "partial"
    assert finished["metrics"]["degraded"] is True
    assert any(isinstance(item, ArchiveRun) for item in fake_session.added)


@pytest.mark.asyncio
async def test_agent_e_weekly_partial_when_sentiment_upstream_errors(monkeypatch) -> None:
    fake_session = _FakeSession(
        queue=[
            _Result(rows=[]),  # preload report rows
            _Result(rows=[]),  # preload sentiment rows
            _Result(rows=[]),  # preload announcements rows
            _Result(),  # outcome insert
            _Result(scalar=None),  # accuracy existing
            _Result(rows=[]),  # accuracy rows
            _Result(rows=[]),  # pattern rows
            _Result(rows=[]),  # impact rows
            _Result(scalar=None),  # archive existing
        ],
        added=[],
    )
    finished: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_get_session():
        yield fake_session

    async def fake_start_run(_agent_name: str, run_id: str | None = None):
        return run_id or "44444444-4444-4444-4444-444444444444"

    async def fake_finish_run(run_id, status, **kwargs):
        finished["run_id"] = run_id
        finished["status"] = status
        finished["metrics"] = kwargs.get("metrics") or {}

    monkeypatch.setattr(archivist_pipeline, "get_session", fake_get_session)
    monkeypatch.setattr(archivist_pipeline, "start_run", fake_start_run)
    monkeypatch.setattr(archivist_pipeline, "finish_run", fake_finish_run)
    monkeypatch.setattr(archivist_pipeline, "_fetch_json", _fake_fetch_json_sentiment_error)
    monkeypatch.setattr(archivist_pipeline.settings, "ARCHIVIST_INPUT_MODE", "hybrid")
    monkeypatch.setattr(archivist_pipeline, "_compute_announcement_impact", _none_impact)
    monkeypatch.setattr(archivist_pipeline, "_upsert_pattern", _noop_upsert_pattern)
    monkeypatch.setattr(archivist_pipeline, "_apply_pattern_lifecycle", _noop_apply_lifecycle)
    monkeypatch.setattr(archivist_pipeline, "publish_archivist_patterns_updated", _noop_publish)
    monkeypatch.setattr(archivist_pipeline, "send_archive_email", _send_ok)

    result = await archivist_pipeline.run_archivist_pipeline(run_type="weekly", period_key=date(2026, 3, 2))
    assert result["status"] == "partial"
    assert finished["status"] == "partial"
    assert finished["metrics"]["degraded"] is True
    assert "no_sentiment_rows" in finished["metrics"]["warnings"]
    assert any(isinstance(item, ArchiveRun) for item in fake_session.added)


@pytest.mark.asyncio
async def test_agent_e_resend_idempotency_skips_without_force(monkeypatch) -> None:
    existing_archive = ArchiveRun(
        run_type="weekly",
        period_key=date(2026, 3, 2),
        status="sent",
        summary={},
        html_content="<html></html>",
        email_sent_at=datetime(2026, 3, 2, 7, 0, tzinfo=timezone.utc),
        email_error=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    fake_session = _FakeSession(
        queue=[
            _Result(rows=[]),  # preload report rows
            _Result(rows=[]),  # preload sentiment rows
            _Result(rows=[]),  # preload announcements rows
            _Result(),  # outcome insert
            _Result(scalar=None),  # accuracy existing
            _Result(rows=[]),  # accuracy rows
            _Result(rows=[]),  # pattern rows
            _Result(rows=[]),  # impact rows
            _Result(scalar=existing_archive),  # archive existing
        ],
        added=[],
    )
    finished: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_get_session():
        yield fake_session

    async def fake_start_run(_agent_name: str, run_id: str | None = None):
        return run_id or "33333333-3333-3333-3333-333333333333"

    async def fake_finish_run(run_id, status, **kwargs):
        finished["run_id"] = run_id
        finished["status"] = status
        finished["metrics"] = kwargs.get("metrics") or {}

    def fail_if_send(*_args, **_kwargs):
        raise AssertionError("send_archive_email should not be called when artifact already sent and force_send=false")

    monkeypatch.setattr(archivist_pipeline, "get_session", fake_get_session)
    monkeypatch.setattr(archivist_pipeline, "start_run", fake_start_run)
    monkeypatch.setattr(archivist_pipeline, "finish_run", fake_finish_run)
    monkeypatch.setattr(archivist_pipeline, "_fetch_json", _fake_fetch_json)
    monkeypatch.setattr(archivist_pipeline, "_compute_announcement_impact", _none_impact)
    monkeypatch.setattr(archivist_pipeline, "_upsert_pattern", _noop_upsert_pattern)
    monkeypatch.setattr(archivist_pipeline, "_apply_pattern_lifecycle", _noop_apply_lifecycle)
    monkeypatch.setattr(archivist_pipeline, "publish_archivist_patterns_updated", _noop_publish)
    monkeypatch.setattr(archivist_pipeline, "send_archive_email", fail_if_send)

    result = await archivist_pipeline.run_archivist_pipeline(
        run_type="weekly",
        period_key=date(2026, 3, 2),
        force_send=False,
    )
    assert result["status"] == "success"
    assert finished["metrics"]["email_skipped"] is True
    assert finished["metrics"]["email_sent"] is False
