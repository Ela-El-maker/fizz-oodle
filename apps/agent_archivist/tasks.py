from __future__ import annotations

import asyncio
from datetime import date

from celery_app import celery_app
from apps.agents.archivist.pipeline import run_archivist_pipeline


@celery_app.task(name="agent_archivist.run", bind=True, max_retries=3, default_retry_delay=600)
def run_archivist(
    self,
    run_id: str | None = None,
    run_type: str | None = None,
    period_key: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
):
    parsed_period_key = date.fromisoformat(period_key) if period_key else None
    return asyncio.run(
        run_archivist_pipeline(
            run_id=run_id,
            run_type=run_type,
            period_key=parsed_period_key,
            force_send=force_send,
            email_recipients_override=email_recipients_override,
        )
    )
