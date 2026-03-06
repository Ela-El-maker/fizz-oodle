from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.core import events as events_module


@pytest.mark.asyncio
async def test_publish_analyst_event_rejects_invalid_schema(monkeypatch) -> None:
    async def fail_publish(_stream: str, _payload: dict):
        raise AssertionError("publish_event should not run for invalid payload")

    monkeypatch.setattr(events_module, "publish_event", fail_publish)

    with pytest.raises(ValidationError):
        await events_module.publish_analyst_report_generated(
            {
                # missing report_id
                "report_type": "daily",
                "period_key": "2026-03-02",
                "degraded": False,
                "generated_at": "2026-03-02T00:00:00+00:00",
            }
        )


@pytest.mark.asyncio
async def test_publish_archivist_event_rejects_invalid_schema(monkeypatch) -> None:
    async def fail_publish(_stream: str, _payload: dict):
        raise AssertionError("publish_event should not run for invalid payload")

    monkeypatch.setattr(events_module, "publish_event", fail_publish)

    with pytest.raises(ValidationError):
        await events_module.publish_archivist_patterns_updated(
            {
                "run_type": "weekly",
                # missing period_key
                "patterns_upserted": 1,
                "impacts_upserted": 1,
                "accuracy_rows_upserted": 1,
                "generated_at": "2026-03-02T00:00:00+00:00",
                "degraded": False,
            }
        )
