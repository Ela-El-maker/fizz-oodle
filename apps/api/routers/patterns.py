from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, desc, select

from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.models import ArchiveRun, ImpactStat, Pattern

router = APIRouter(tags=["patterns"])


@router.get("/patterns")
async def list_patterns(
    ticker: str | None = None,
    status: str | None = None,
    min_accuracy: float | None = None,
    limit: int = 100,
    _auth: None = Depends(require_api_key),
):
    safe_limit = max(1, min(limit, 500))
    async with get_session() as session:
        stmt = select(Pattern).order_by(desc(Pattern.updated_at)).limit(safe_limit)
        if ticker:
            stmt = stmt.where(Pattern.ticker == ticker.upper())
        if status:
            stmt = stmt.where(Pattern.status == status.lower())
        if min_accuracy is not None:
            stmt = stmt.where(Pattern.accuracy_pct >= float(min_accuracy))
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "items": [
            {
                "pattern_id": str(r.pattern_id),
                "ticker": r.ticker,
                "pattern_type": r.pattern_type,
                "description": r.description,
                "status": r.status,
                "confidence_pct": r.confidence_pct,
                "accuracy_pct": r.accuracy_pct,
                "occurrence_count": r.occurrence_count,
                "avg_impact_1d": r.avg_impact_1d,
                "avg_impact_5d": r.avg_impact_5d,
                "active": r.active,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


@router.get("/patterns/ticker/{ticker}")
async def patterns_by_ticker(ticker: str, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        rows = (
            await session.execute(select(Pattern).where(Pattern.ticker == ticker.upper()).order_by(desc(Pattern.updated_at)))
        ).scalars().all()
    return {"ticker": ticker.upper(), "items": [{"pattern_id": str(r.pattern_id), "type": r.pattern_type, "status": r.status, "accuracy_pct": r.accuracy_pct, "description": r.description} for r in rows]}


@router.get("/patterns/active")
async def list_active_patterns(limit: int = 100, _auth: None = Depends(require_api_key)):
    safe_limit = max(1, min(limit, 500))
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Pattern)
                .where(and_(Pattern.active.is_(True), Pattern.status == "confirmed"))
                .order_by(desc(Pattern.accuracy_pct), desc(Pattern.updated_at))
                .limit(safe_limit)
            )
        ).scalars().all()
    return {"items": [{"pattern_id": str(r.pattern_id), "ticker": r.ticker, "pattern_type": r.pattern_type, "accuracy_pct": r.accuracy_pct, "confidence_pct": r.confidence_pct, "description": r.description} for r in rows]}


@router.get("/patterns/summary")
async def pattern_summary(_auth: None = Depends(require_api_key)):
    async with get_session() as session:
        all_rows = (await session.execute(select(Pattern))).scalars().all()
    total = len(all_rows)
    confirmed = len([r for r in all_rows if r.status == "confirmed"])
    candidates = len([r for r in all_rows if r.status == "candidate"])
    retired = len([r for r in all_rows if r.status == "retired"])
    return {
        "total": total,
        "confirmed": confirmed,
        "candidate": candidates,
        "retired": retired,
        "active": len([r for r in all_rows if r.active]),
    }


@router.get("/impacts/{announcement_type}")
async def impact_by_announcement_type(
    announcement_type: str,
    period_key: str | None = None,
    _auth: None = Depends(require_api_key),
):
    parsed_period = date.fromisoformat(period_key) if period_key else None
    async with get_session() as session:
        stmt = select(ImpactStat).where(ImpactStat.announcement_type == announcement_type)
        if parsed_period:
            stmt = stmt.where(ImpactStat.period_key == parsed_period)
        stmt = stmt.order_by(desc(ImpactStat.period_key)).limit(1)
        row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No impact stats found")
    return {
        "announcement_type": row.announcement_type,
        "period_key": row.period_key.isoformat(),
        "sample_count": row.sample_count,
        "avg_change_1d": row.avg_change_1d,
        "avg_change_5d": row.avg_change_5d,
        "avg_change_30d": row.avg_change_30d,
        "positive_rate": row.positive_rate,
        "negative_rate": row.negative_rate,
        "details": row.details or {},
    }


@router.get("/archive/latest")
async def latest_archive(run_type: str = "weekly", _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        row = (
            await session.execute(
                select(ArchiveRun).where(ArchiveRun.run_type == run_type).order_by(desc(ArchiveRun.period_key)).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No archive run found")
    summary = row.summary or {}
    human_summary = None
    human_summary_v2 = None
    if isinstance(summary, dict):
        raw = summary.get("human_summary")
        human_summary = raw if isinstance(raw, dict) else None
        raw_v2 = summary.get("human_summary_v2")
        human_summary_v2 = raw_v2 if isinstance(raw_v2, dict) else None
    return {
        "run_type": row.run_type,
        "period_key": row.period_key.isoformat(),
        "status": row.status,
        "summary": summary,
        "human_summary": human_summary,
        "human_summary_v2": human_summary_v2,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
