from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from celery_app import celery_app

from apps.core.logger import get_logger
from apps.core.run_service import fail_run, finish_run, start_run

logger = get_logger(__name__)


@celery_app.task(name="agent_system.ping", bind=True, max_retries=2, default_retry_delay=60)
def run_system_ping(self, run_id: str | None = None):
    return asyncio.run(_run(run_id=run_id))


async def _run(run_id: str | None = None):
    rid = await start_run("system", run_id=run_id)

    try:
        metrics = {
            "ping": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await finish_run(rid, status="success", metrics=metrics, records_processed=1)
        return {"run_id": rid, "ok": True}

    except Exception as e:
        logger.exception("run_failed", run_id=rid, agent_name="system", error=str(e))
        await fail_run(rid, error_message=str(e), metrics={"ping": False})
        raise
