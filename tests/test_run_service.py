from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import pytest

from apps.core import run_service


class FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeSession:
    def __init__(self, row=None):
        self.row = row
        self.added = []
        self.commits = 0

    async def execute(self, _stmt):
        return FakeResult(self.row)

    def add(self, obj):
        self.added.append(obj)
        self.row = obj

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_start_and_finish_run_lifecycle(monkeypatch):
    session = FakeSession(row=None)
    monkeypatch.setattr(run_service.settings, "RUN_DB_WRITE_ENABLED", True)

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(run_service, "get_session", fake_get_session)

    run_id = await run_service.start_run("system")
    UUID(run_id)  # must be a valid UUID

    assert len(session.added) == 1
    run = session.added[0]
    assert run.agent_name == "system"
    assert run.status == "running"

    await run_service.finish_run(
        run_id,
        status="success",
        metrics={"ping": True},
        records_processed=1,
        records_new=0,
        errors_count=0,
    )

    assert run.status == "success"
    assert run.metrics == {"ping": True}
    assert run.records_processed == 1
    assert run.records_new == 0
    assert run.errors_count == 0
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_fail_run_sets_terminal_state(monkeypatch):
    session = FakeSession(row=None)
    monkeypatch.setattr(run_service.settings, "RUN_DB_WRITE_ENABLED", True)

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(run_service, "get_session", fake_get_session)

    run_id = await run_service.start_run("announcements")
    run = session.row

    await run_service.fail_run(run_id, error_message="boom", metrics={"source": "nse"})

    assert run.status == "fail"
    assert run.error_message == "boom"
    assert run.metrics == {"source": "nse"}
    assert run.errors_count == 1


@pytest.mark.asyncio
async def test_finish_run_rejects_non_terminal_status(monkeypatch):
    session = FakeSession(row=None)
    monkeypatch.setattr(run_service.settings, "RUN_DB_WRITE_ENABLED", True)

    @asynccontextmanager
    async def fake_get_session():
        yield session

    monkeypatch.setattr(run_service, "get_session", fake_get_session)
    run_id = await run_service.start_run("briefing")

    with pytest.raises(ValueError, match="terminal status"):
        await run_service.finish_run(run_id, status="running")
