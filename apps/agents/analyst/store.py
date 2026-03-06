from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.models import AnalystReport


def should_send(existing: AnalystReport | None, force_send: bool) -> tuple[bool, bool]:
    if force_send:
        return True, False
    if existing is not None and existing.email_sent_at is not None:
        return False, True
    return True, False


async def get_report_by_key(session: AsyncSession, report_type: str, period_key: date) -> AnalystReport | None:
    return (
        await session.execute(
            select(AnalystReport).where(
                and_(AnalystReport.report_type == report_type, AnalystReport.period_key == period_key)
            )
        )
    ).scalar_one_or_none()


async def upsert_report(
    session: AsyncSession,
    report_type: str,
    period_key: date,
    subject: str,
    html_content: str,
    json_payload: dict,
    inputs_summary: dict,
    metrics: dict,
    payload_hash: str,
    status: str,
    email_sent_at: datetime | None,
    email_error: str | None,
    llm_used: bool,
    degraded: bool,
) -> AnalystReport:
    row = await get_report_by_key(session, report_type=report_type, period_key=period_key)
    if row is None:
        row = AnalystReport(
            report_type=report_type,
            period_key=period_key,
            generated_at=datetime.now(timezone.utc),
            status=status,
            subject=subject,
            html_content=html_content,
            json_payload=json_payload,
            inputs_summary=inputs_summary,
            metrics=metrics,
            email_sent_at=email_sent_at,
            email_error=email_error,
            payload_hash=payload_hash,
            llm_used=llm_used,
            degraded=degraded,
        )
        session.add(row)
        return row

    row.generated_at = datetime.now(timezone.utc)
    row.status = status
    row.subject = subject
    row.html_content = html_content
    row.json_payload = json_payload
    row.inputs_summary = inputs_summary
    row.metrics = metrics
    row.email_sent_at = email_sent_at
    row.email_error = email_error
    row.payload_hash = payload_hash
    row.llm_used = llm_used
    row.degraded = degraded
    return row
