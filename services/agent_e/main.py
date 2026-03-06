from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import and_, desc, select

from apps.api.routers.patterns import router as patterns_router
from apps.core.database import get_session
from apps.core.logger import configure_logging
from apps.core.models import ArchiveRun, ImpactStat, Pattern
from services.common.commands import command_listener
from services.common.metrics import setup_metrics
from services.common.internal_router import build_internal_router
from services.common.security import require_internal_api_key

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(command_listener("archivist", stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Agent E Service", lifespan=lifespan)
setup_metrics(app, "agent_e")
app.include_router(build_internal_router("archivist"))
app.include_router(patterns_router)


@app.get("/internal/data/latest", dependencies=[Depends(require_internal_api_key)])
async def internal_data_latest(announcement_type: str | None = None):
    async with get_session() as session:
        active_patterns = (
            await session.execute(
                select(Pattern)
                .where(and_(Pattern.active.is_(True), Pattern.status == "confirmed"))
                .order_by(desc(Pattern.accuracy_pct), desc(Pattern.updated_at))
                .limit(10)
            )
        ).scalars().all()

        impact_stmt = select(ImpactStat).order_by(desc(ImpactStat.period_key)).limit(10)
        if announcement_type:
            impact_stmt = (
                select(ImpactStat)
                .where(ImpactStat.announcement_type == announcement_type)
                .order_by(desc(ImpactStat.period_key))
                .limit(10)
            )
        impacts = (await session.execute(impact_stmt)).scalars().all()

        weekly_archive = (
            await session.execute(
                select(ArchiveRun).where(ArchiveRun.run_type == "weekly").order_by(desc(ArchiveRun.period_key)).limit(1)
            )
        ).scalars().first()

    return {
        "patterns": [
            {
                "pattern_id": str(p.pattern_id),
                "ticker": p.ticker,
                "pattern_type": p.pattern_type,
                "status": p.status,
                "confidence_pct": p.confidence_pct,
                "accuracy_pct": p.accuracy_pct,
                "occurrence_count": p.occurrence_count,
                "description": p.description,
            }
            for p in active_patterns
        ],
        "impacts": [
            {
                "announcement_type": i.announcement_type,
                "period_key": i.period_key.isoformat(),
                "sample_count": i.sample_count,
                "avg_change_1d": i.avg_change_1d,
                "positive_rate": i.positive_rate,
                "negative_rate": i.negative_rate,
            }
            for i in impacts
        ],
        "archive_latest_weekly": (
            {
                "period_key": weekly_archive.period_key.isoformat(),
                "status": weekly_archive.status,
                "summary": weekly_archive.summary or {},
                "updated_at": weekly_archive.updated_at.isoformat() if weekly_archive.updated_at else None,
            }
            if weekly_archive
            else None
        ),
    }
