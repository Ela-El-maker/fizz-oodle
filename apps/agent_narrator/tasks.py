from __future__ import annotations

import asyncio

from celery_app import celery_app

from apps.agents.narrator.pipeline import run_narrator_pipeline


@celery_app.task(name="agent_narrator.run", bind=True, max_retries=2, default_retry_delay=180)
def run_narrator(
    self,
    run_id: str | None = None,
    force_send: bool | None = None,
):
    return asyncio.run(run_narrator_pipeline(run_id=run_id, force_regenerate=force_send))
