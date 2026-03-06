from __future__ import annotations

import asyncio
from datetime import date

from celery_app import celery_app
from apps.agents.analyst.pipeline import run_analyst_pipeline


@celery_app.task(name="agent_analyst.run", bind=True, max_retries=3, default_retry_delay=600)
def run_analyst(
    self,
    run_id: str | None = None,
    report_type: str | None = None,
    period_key: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
):
    parsed_period_key = date.fromisoformat(period_key) if period_key else None
    return asyncio.run(
        run_analyst_pipeline(
            run_id=run_id,
            report_type=report_type,
            period_key=parsed_period_key,
            force_send=force_send,
            email_recipients_override=email_recipients_override,
        )
    )
