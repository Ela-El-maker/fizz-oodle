from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import desc, select

from apps.api.routers.admin_reports import router as admin_reports_router
from apps.api.routers.reports import router as reports_router
from apps.core.database import get_session
from apps.core.logger import configure_logging
from apps.core.models import AnalystReport
from services.common.commands import command_listener
from services.common.metrics import setup_metrics
from services.common.internal_router import build_internal_router
from services.common.security import require_internal_api_key

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(command_listener("analyst", stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Agent D Service", lifespan=lifespan)
setup_metrics(app, "agent_d")
app.include_router(build_internal_router("analyst"))
app.include_router(reports_router)
app.include_router(admin_reports_router)


@app.get("/internal/data/latest", dependencies=[Depends(require_internal_api_key)])
async def internal_data_latest(report_type: str | None = None):
    async with get_session() as session:
        stmt = select(AnalystReport).order_by(desc(AnalystReport.generated_at)).limit(1)
        if report_type:
            stmt = (
                select(AnalystReport)
                .where(AnalystReport.report_type == report_type)
                .order_by(desc(AnalystReport.generated_at))
                .limit(1)
            )
        row = (await session.execute(stmt)).scalars().first()

    if row is None:
        return {"item": None}

    return {
        "item": {
            "report_id": str(row.report_id),
            "report_type": row.report_type,
            "period_key": row.period_key.isoformat(),
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "status": row.status,
            "degraded": bool(row.degraded),
            "metrics": row.metrics or {},
        }
    }
