from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, select

from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.models import AnalystReport

router = APIRouter(tags=["reports"], dependencies=[Depends(require_api_key)])


def _serialize_report(row: AnalystReport) -> dict:
    metrics = row.metrics or {}
    human_summary = metrics.get("human_summary") if isinstance(metrics, dict) else None
    human_summary_v2 = metrics.get("human_summary_v2") if isinstance(metrics, dict) else None
    return {
        "report_id": str(row.report_id),
        "report_type": row.report_type,
        "period_key": str(row.period_key),
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "status": row.status,
        "subject": row.subject,
        "html_content": row.html_content,
        "json_payload": row.json_payload or {},
        "inputs_summary": row.inputs_summary or {},
        "metrics": metrics,
        "human_summary": human_summary if isinstance(human_summary, dict) else None,
        "human_summary_v2": human_summary_v2 if isinstance(human_summary_v2, dict) else None,
        "email_sent_at": row.email_sent_at.isoformat() if row.email_sent_at else None,
        "email_error": row.email_error,
        "payload_hash": row.payload_hash,
        "llm_used": row.llm_used,
        "degraded": row.degraded,
    }


@router.get("/reports/latest")
async def reports_latest(type: str = Query(default="daily")):  # noqa: A002
    report_type = type.strip().lower()
    if report_type not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="type must be daily|weekly")

    async with get_session() as session:
        row = (
            await session.execute(
                select(AnalystReport)
                .where(AnalystReport.report_type == report_type)
                .order_by(desc(AnalystReport.period_key))
                .limit(1)
            )
        ).scalars().first()

    if row is None:
        return {"item": None}
    return {"item": _serialize_report(row)}


@router.get("/reports")
async def reports_list(
    type: str | None = Query(default=None),  # noqa: A002
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    async with get_session() as session:
        stmt = select(AnalystReport)

        if type:
            report_type = type.strip().lower()
            if report_type not in {"daily", "weekly"}:
                raise HTTPException(status_code=400, detail="type must be daily|weekly")
            stmt = stmt.where(AnalystReport.report_type == report_type)
        if from_date:
            stmt = stmt.where(AnalystReport.period_key >= from_date)
        if to_date:
            stmt = stmt.where(AnalystReport.period_key <= to_date)

        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        rows = (
            await session.execute(
                stmt.order_by(AnalystReport.period_key.desc(), AnalystReport.generated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()

    return {
        "items": [_serialize_report(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/reports/{report_id}")
async def report_get(report_id: str):
    try:
        report_uuid = UUID(report_id)
    except Exception as exc:  # noqa: PERF203
        raise HTTPException(status_code=400, detail="Invalid report_id") from exc

    async with get_session() as session:
        row = (
            await session.execute(select(AnalystReport).where(AnalystReport.report_id == report_uuid).limit(1))
        ).scalars().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"item": _serialize_report(row)}


@router.get("/reports/{report_id}/inputs")
async def report_inputs(report_id: str):
    try:
        report_uuid = UUID(report_id)
    except Exception as exc:  # noqa: PERF203
        raise HTTPException(status_code=400, detail="Invalid report_id") from exc

    async with get_session() as session:
        row = (
            await session.execute(select(AnalystReport).where(AnalystReport.report_id == report_uuid).limit(1))
        ).scalars().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")

    return {
        "report_id": str(row.report_id),
        "report_type": row.report_type,
        "period_key": str(row.period_key),
        "inputs_summary": row.inputs_summary or {},
    }
