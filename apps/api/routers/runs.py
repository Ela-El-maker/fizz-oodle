from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy import select

from celery_app import celery_app
from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.logger import get_logger
from apps.core.models import AgentRun
from apps.core.run_service import fail_run, start_run

logger = get_logger(__name__)

router = APIRouter(tags=["runs"])

RUN_STATUSES = {"running", "success", "partial", "fail"}

AGENT_TASK_MAP = {
    "system": "agent_system.ping",
    "announcements": "agent_announcements.run",
    "briefing": "agent_briefing.run",
    "sentiment": "agent_sentiment.run",
    "analyst": "agent_analyst.run",
    "archivist": "agent_archivist.run",
    "narrator": "agent_narrator.run",
}


@router.get("/runs")
async def list_runs(agent_name: str | None = None, status: str | None = None, limit: int = 50):
    normalized_limit = max(1, min(limit, 200))
    if status and status not in RUN_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {sorted(RUN_STATUSES)}")

    async with get_session() as session:
        stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(normalized_limit)
        if agent_name:
            stmt = stmt.where(AgentRun.agent_name == agent_name)
        if status:
            stmt = stmt.where(AgentRun.status == status)

        rows = (await session.execute(stmt)).scalars().all()

    items = [
        {
            "run_id": str(r.run_id),
            "agent_name": r.agent_name,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "metrics": r.metrics or {},
            "error_message": r.error_message,
            "records_processed": int(getattr(r, "records_processed", 0) or 0),
            "records_new": int(getattr(r, "records_new", 0) or 0),
            "errors_count": int(getattr(r, "errors_count", 0) or 0),
            "status_reason": (r.metrics or {}).get("status_reason") or getattr(r, "error_message", None),
            "is_stale_reconciled": bool((r.metrics or {}).get("stale_reconciled")),
        }
        for r in rows
    ]

    return {"items": items}


@router.post("/run/{agent}", status_code=http_status.HTTP_202_ACCEPTED)
async def trigger_run(agent: str, _auth: None = Depends(require_api_key)):
    task_name = AGENT_TASK_MAP.get(agent)
    if not task_name:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {agent}")

    run_id = await start_run(agent)

    try:
        celery_app.send_task(task_name, kwargs={"run_id": run_id})
    except Exception as e:
        await fail_run(run_id, error_message=f"enqueue_failed: {e}")
        logger.exception("run_failed", run_id=run_id, agent_name=agent, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to enqueue task") from e

    return {
        "run_id": run_id,
        "agent_name": agent,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "metrics": {},
    }
