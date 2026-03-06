from __future__ import annotations

from uuid import uuid4

from apps.core.models import AgentRun


def test_agent_run_legacy_aliases_and_status() -> None:
    run = AgentRun(run_id=uuid4(), agent_name="system", status="running", metrics={"ping": True})

    assert run.outcome == "running"

    run.outcome = "partial"
    assert run.status == "partial"

    assert run.legacy_metadata == {"ping": True}
