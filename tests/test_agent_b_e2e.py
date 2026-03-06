from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from apps.agents.announcements import pipeline
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.core import database as db
from apps.core.database import Base, get_session
from apps.core.models import Announcement, SourceHealth


async def _db_ready() -> bool:
    try:
        async with db._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _reset_db() -> None:
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE TABLE announcement_assets, announcements, source_health, agent_runs, companies RESTART IDENTITY CASCADE"))


@pytest.mark.asyncio
async def test_agent_b_e2e_ingest_idempotent_partial_and_email_failure(monkeypatch) -> None:
    if not await _db_ready():
        pytest.skip("Postgres not available for e2e")

    await _reset_db()

    async def fake_seed_companies():
        return None

    source_ok = SourceConfig(
        source_id="nse_official",
        type="official",
        base_url="https://example.com",
        enabled_by_default=True,
        parser="x",
        timeout_secs=10,
        retries=0,
        backoff_base=2.0,
        rate_limit_rps=1.0,
        ticker_strategy="headline_regex",
    )
    source_bad = SourceConfig(
        source_id="cma_notices",
        type="regulator",
        base_url="https://bad.example",
        enabled_by_default=True,
        parser="y",
        timeout_secs=10,
        retries=0,
        backoff_base=2.0,
        rate_limit_rps=1.0,
        ticker_strategy="headline_regex",
        tier="core",
        required_for_success=True,
    )

    raw_one = RawAnnouncement(
        source_id="nse_official",
        headline="Safaricom interim dividend declared",
        url="https://example.com/a1?utm_source=x",
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ticker_hint="SCOM",
        extra={"k": "v"},
    )

    raw_two = RawAnnouncement(
        source_id="nse_official",
        headline="KCB board change notice",
        url="https://example.com/a2",
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        ticker_hint="KCB",
        extra={"k": "v2"},
    )

    async def collector_ok(_source):
        return [raw_one]

    async def collector_ok_two(_source):
        return [raw_two]

    async def collector_bad(_source):
        raise RuntimeError("source unavailable")

    def get_collector_single(_source):
        return collector_ok

    def get_collector_mixed(source):
        return collector_bad if source.source_id == "cma_notices" else collector_ok

    def get_collector_email_failure(_source):
        return collector_ok_two

    monkeypatch.setattr(pipeline, "seed_companies", fake_seed_companies)
    monkeypatch.setattr(pipeline.settings, "EMAIL_ALERTS_HIGH_IMPACT_ONLY", False)

    async def fake_extract_details(_url: str):
        return "details"

    monkeypatch.setattr(pipeline, "extract_details", fake_extract_details)

    # 1) happy path: ingest + send + mark alerted
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok])
    monkeypatch.setattr(pipeline, "get_collector", get_collector_single)
    monkeypatch.setattr(pipeline, "send_announcements_email", lambda _items, run_id: (True, None))

    result_1 = await pipeline.run_announcements_pipeline()
    assert result_1["status"] == "success"

    async with get_session() as session:
        rows = (await session.execute(text("SELECT COUNT(*) FROM announcements"))).scalar_one()
        alerted = (await session.execute(text("SELECT COUNT(*) FROM announcements WHERE alerted=true"))).scalar_one()
    assert rows == 1
    assert alerted == 1

    # 2) rerun idempotent: no new rows, no new alert
    result_2 = await pipeline.run_announcements_pipeline()
    assert result_2["status"] == "success"
    assert result_2["records_new"] == 0
    assert result_2["metrics"]["new_alert_count"] == 0

    # 2b) force-send path with no new candidates uses validation fallback rows
    fallback_capture = {}

    def fake_force_send(items, run_id, recipients=None):
        fallback_capture["count"] = len(items)
        fallback_capture["run_id"] = run_id
        fallback_capture["recipients"] = recipients
        return True, None

    monkeypatch.setattr(pipeline, "send_announcements_email", fake_force_send)
    result_2b = await pipeline.run_announcements_pipeline(force_send=True, email_recipients_override="qa@example.com")
    assert result_2b["status"] == "success"
    assert result_2b["metrics"]["new_alert_count"] == 0
    assert result_2b["metrics"]["email_validation_fallback"] is True
    assert result_2b["metrics"]["email_sent"] is True
    assert fallback_capture["count"] >= 1
    assert fallback_capture["recipients"] == "qa@example.com"

    # 3) partial failure: one source fails, other still processed
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok, source_bad])
    monkeypatch.setattr(pipeline, "get_collector", get_collector_mixed)
    monkeypatch.setattr(pipeline.settings, "SOURCE_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(pipeline.settings, "SOURCE_COOLDOWN_MINUTES", 30)

    result_3 = await pipeline.run_announcements_pipeline()
    assert result_3["status"] == "partial"
    assert "error" in result_3["metrics"]["sources"]["cma_notices"]

    # 4) email failure: new announcement inserted but remains unalerted
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok])
    monkeypatch.setattr(pipeline, "get_collector", get_collector_email_failure)
    monkeypatch.setattr(pipeline, "send_announcements_email", lambda _items, run_id: (False, "smtp_down"))

    result_4 = await pipeline.run_announcements_pipeline()
    assert result_4["status"] == "fail"

    async with get_session() as session:
        new_row = (
            await session.execute(
                text("SELECT alerted FROM announcements WHERE url='https://example.com/a2' LIMIT 1")
            )
        ).scalar_one()
    assert new_row is False

    # 5) breaker opens after repeated failures
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_bad])
    monkeypatch.setattr(pipeline, "get_collector", lambda _s: collector_bad)
    await pipeline.run_announcements_pipeline()
    await pipeline.run_announcements_pipeline()

    async with get_session() as session:
        breaker_state = (
            await session.execute(text("SELECT breaker_state FROM source_health WHERE source_id='cma_notices'"))
        ).scalar_one()
    assert breaker_state == "open"
