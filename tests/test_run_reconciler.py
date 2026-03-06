from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.run_ledger.main import _is_stale_running_run


def test_running_announcements_run_marked_stale_when_older_than_ttl(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        status="running",
        agent_name="announcements",
        started_at=now - timedelta(minutes=25),
    )

    import services.run_ledger.main as run_ledger_main

    monkeypatch.setattr(run_ledger_main.settings, "ANNOUNCEMENTS_STALE_RUN_TTL_MINUTES", 20)
    assert _is_stale_running_run(row, now) is True


def test_non_running_or_recent_runs_not_stale(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    running_recent = SimpleNamespace(
        status="running",
        agent_name="announcements",
        started_at=now - timedelta(minutes=5),
    )
    finished_old = SimpleNamespace(
        status="success",
        agent_name="announcements",
        started_at=now - timedelta(hours=2),
    )

    import services.run_ledger.main as run_ledger_main

    monkeypatch.setattr(run_ledger_main.settings, "ANNOUNCEMENTS_STALE_RUN_TTL_MINUTES", 20)
    assert _is_stale_running_run(running_recent, now) is False
    assert _is_stale_running_run(finished_old, now) is False


def test_running_briefing_run_marked_stale_with_agent_specific_ttl(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        status="running",
        agent_name="briefing",
        started_at=now - timedelta(minutes=40),
    )

    import services.run_ledger.main as run_ledger_main

    monkeypatch.setattr(run_ledger_main.settings, "BRIEFING_STALE_RUN_TTL_MINUTES", 30)
    assert _is_stale_running_run(row, now) is True
