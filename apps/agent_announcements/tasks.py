from __future__ import annotations

import asyncio

from celery_app import celery_app

from apps.agents.announcements.pipeline import run_announcements_pipeline


@celery_app.task(name="agent_announcements.run", bind=True, max_retries=3, default_retry_delay=300)
def run_announcements_monitor(
    self,
    run_id: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
):
    return asyncio.run(
        run_announcements_pipeline(
            run_id=run_id,
            force_send=force_send,
            email_recipients_override=email_recipients_override,
        )
    )
