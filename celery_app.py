from __future__ import annotations

from pathlib import Path
import logging

from celery import Celery
from celery.schedules import crontab
import yaml

from apps.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


ALLOWED_TASKS = {
    "agent_system.ping",
    "agent_announcements.run",
    "agent_briefing.run",
    "agent_sentiment.run",
    "agent_analyst.run",
    "agent_archivist.run",
    "agent_narrator.run",
}


def _parse_utc_cron(expr: str) -> crontab:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr}")

    minute, hour, day_of_month, month_of_year, day_of_week = parts
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def _load_beat_schedule_from_config(path: str) -> dict:
    schedule_path = Path(path)
    if not schedule_path.is_absolute():
        schedule_path = (Path(__file__).resolve().parent / schedule_path).resolve()
    if not schedule_path.exists():
        logger.warning("schedule_config_missing path=%s", str(schedule_path))
        return {}

    with schedule_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    schedules = data.get("schedules", [])
    beat_schedule: dict = {}
    for item in schedules:
        schedule_key = item.get("schedule_key")
        task_name = item.get("task_name")
        utc_cron = item.get("utc_cron")
        task_kwargs = item.get("task_kwargs")

        if not schedule_key or not task_name or not utc_cron:
            logger.warning("schedule_entry_invalid entry=%s", item)
            continue

        if task_name not in ALLOWED_TASKS:
            logger.warning("schedule_task_unknown schedule_key=%s task_name=%s", schedule_key, task_name)
            continue

        try:
            beat_schedule[schedule_key] = {
                "task": task_name,
                "schedule": _parse_utc_cron(utc_cron),
            }
            if isinstance(task_kwargs, dict) and task_kwargs:
                beat_schedule[schedule_key]["kwargs"] = task_kwargs
        except ValueError as e:
            logger.warning("schedule_cron_invalid schedule_key=%s error=%s", schedule_key, str(e))

    return beat_schedule

celery_app = Celery(
    "market_intel",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "apps.agent_system.tasks",
        "apps.agent_briefing.tasks",
        "apps.agent_announcements.tasks",
        "apps.agent_sentiment.tasks",
        "apps.agent_analyst.tasks",
        "apps.agent_archivist.tasks",
        "apps.agent_narrator.tasks",
    ],
)

# Schedules are in UTC. Nairobi is UTC+3.
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = _load_beat_schedule_from_config(settings.SCHEDULES_CONFIG_PATH)

celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_serializer = "json"
celery_app.conf.result_expires = 3600
celery_app.conf.task_default_retry_delay = 300
celery_app.conf.task_default_max_retries = 3
celery_app.conf.task_acks_late = True
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_routes = {
    "agent_system.ping": {"queue": "system"},
    "agent_announcements.run": {"queue": "agent_b"},
    "agent_briefing.run": {"queue": "agent_a"},
    "agent_sentiment.run": {"queue": "agent_c"},
    "agent_analyst.run": {"queue": "agent_d"},
    "agent_archivist.run": {"queue": "agent_e"},
    "agent_narrator.run": {"queue": "agent_f"},
}
