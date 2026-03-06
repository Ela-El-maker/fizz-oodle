from __future__ import annotations

import asyncio
from datetime import date

from celery_app import celery_app
from apps.agents.sentiment.pipeline import run_sentiment_pipeline


@celery_app.task(name="agent_sentiment.run", bind=True, max_retries=3, default_retry_delay=600)
def run_weekly_sentiment(
    self,
    run_id: str | None = None,
    week_start: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
):
    parsed_week_start = date.fromisoformat(week_start) if week_start else None
    return asyncio.run(
        run_sentiment_pipeline(
            run_id=run_id,
            week_start_override=parsed_week_start,
            force_send=force_send,
            email_recipients_override=email_recipients_override,
        )
    )
