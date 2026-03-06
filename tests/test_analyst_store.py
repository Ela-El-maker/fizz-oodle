from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from apps.agents.analyst.store import get_report_by_key, should_send, upsert_report
from apps.core import database as db
from apps.core.database import Base, get_session


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
        await conn.execute(text("TRUNCATE TABLE analyst_reports RESTART IDENTITY CASCADE"))


def test_should_send_logic() -> None:
    send_now, skipped = should_send(existing=None, force_send=False)
    assert send_now is True
    assert skipped is False

    class Existing:
        email_sent_at = datetime.now(timezone.utc)

    send_now, skipped = should_send(existing=Existing(), force_send=False)
    assert send_now is False
    assert skipped is True

    send_now, skipped = should_send(existing=Existing(), force_send=True)
    assert send_now is True
    assert skipped is False


@pytest.mark.asyncio
async def test_upsert_report_idempotent_by_type_period() -> None:
    if not await _db_ready():
        pytest.skip("Postgres not available for analyst store test")

    await _reset_db()

    async with get_session() as session:
        await upsert_report(
            session=session,
            report_type="daily",
            period_key=date(2026, 3, 1),
            subject="Daily",
            html_content="<p>v1</p>",
            json_payload={"v": 1},
            inputs_summary={"a": 1},
            metrics={"m": 1},
            payload_hash="h1",
            status="generated",
            email_sent_at=None,
            email_error=None,
            llm_used=False,
            degraded=False,
        )
        await session.commit()

    async with get_session() as session:
        await upsert_report(
            session=session,
            report_type="daily",
            period_key=date(2026, 3, 1),
            subject="Daily v2",
            html_content="<p>v2</p>",
            json_payload={"v": 2},
            inputs_summary={"a": 2},
            metrics={"m": 2},
            payload_hash="h2",
            status="sent",
            email_sent_at=datetime.now(timezone.utc),
            email_error=None,
            llm_used=False,
            degraded=False,
        )
        await session.commit()

    async with get_session() as session:
        row = await get_report_by_key(session, report_type="daily", period_key=date(2026, 3, 1))
        count = (await session.execute(text("SELECT COUNT(*) FROM analyst_reports"))).scalar_one()

    assert row is not None
    assert row.subject == "Daily v2"
    assert row.payload_hash == "h2"
    assert count == 1
