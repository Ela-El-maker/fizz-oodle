from __future__ import annotations

import asyncio
import contextlib
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from celery.schedules import crontab
from fastapi import Depends, FastAPI, HTTPException
from prometheus_client import Counter
import httpx
import yaml

from apps.core.config import get_settings
from apps.core.events import publish_run_command
from apps.core.logger import configure_logging, get_logger
from services.common.metrics import setup_metrics
from services.common.security import require_internal_api_key

configure_logging()
logger = get_logger(__name__)
settings = get_settings()
EAT_TZ = ZoneInfo("Africa/Nairobi")


TASK_AGENT_MAP = {
    "agent_briefing.run": "briefing",
    "agent_announcements.run": "announcements",
    "agent_sentiment.run": "sentiment",
    "agent_analyst.run": "analyst",
    "agent_archivist.run": "archivist",
    "agent_narrator.run": "narrator",
}
OPS_TASKS = {"ops.email_validation.run"}


@dataclass
class ScheduledCommand:
    schedule_key: str
    task_name: str
    cron: crontab
    timezone: str
    eat_cron: str | None
    utc_cron: str
    notes: str | None
    task_kwargs: dict
    last_checked: datetime
    enabled: bool


def _parse_utc_cron(expr: str) -> crontab:
    minute, hour, day_of_month, month_of_year, day_of_week = expr.strip().split()
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def _fmt_eat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(EAT_TZ).isoformat()


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _load_schedules() -> list[ScheduledCommand]:
    schedule_path = Path(settings.SCHEDULES_CONFIG_PATH)
    if not schedule_path.is_absolute():
        schedule_path = (Path(__file__).resolve().parents[2] / settings.SCHEDULES_CONFIG_PATH).resolve()
    data = yaml.safe_load(schedule_path.read_text(encoding="utf-8")) or {}
    now = datetime.now(timezone.utc)
    results: list[ScheduledCommand] = []
    for item in data.get("schedules", []):
        task_name = item.get("task_name")
        if task_name not in TASK_AGENT_MAP and task_name not in OPS_TASKS:
            continue
        results.append(
            ScheduledCommand(
                schedule_key=item["schedule_key"],
                task_name=task_name,
                cron=_parse_utc_cron(item["utc_cron"]),
                timezone=str(item.get("timezone") or data.get("timezone") or "Africa/Nairobi"),
                eat_cron=item.get("eat_cron"),
                utc_cron=item.get("utc_cron") or "",
                notes=item.get("notes"),
                task_kwargs=item.get("task_kwargs") or {},
                last_checked=now,
                enabled=bool(item.get("enabled", True)),
            )
        )
    return results


def _estimate_next_run_utc(schedule: ScheduledCommand, now_utc: datetime) -> tuple[datetime | None, float | None]:
    try:
        remaining = schedule.cron.remaining_estimate(now_utc)
        seconds = max(0.0, float(remaining.total_seconds()))
        return now_utc + timedelta(seconds=seconds), seconds
    except Exception:
        return None, None


async def _log_dispatch_to_run_ledger(payload: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.RUN_LEDGER_SERVICE_URL.rstrip('/')}/internal/scheduler/dispatch-log",
                json=payload,
                headers={"X-Internal-Api-Key": settings.INTERNAL_API_KEY},
            )
        resp.raise_for_status()
    except Exception as exc:  # noqa: PERF203
        logger.warning("scheduler_dispatch_log_failed", error=str(exc), payload=payload)


async def _dispatch(
    schedule: ScheduledCommand,
    *,
    trigger_type: str,
    requested_by: str,
    scheduled_for: datetime | None,
    next_run_at: datetime | None,
) -> dict[str, Any]:
    kwargs = schedule.task_kwargs or {}
    dispatched_at = datetime.now(timezone.utc)
    command_id: str | None = None
    run_id: str | None = None
    dispatch_status = "accepted"
    failure_reason: str | None = None

    try:
        if schedule.task_name in OPS_TASKS:
            ops_result = await _dispatch_ops_task(schedule.task_name, kwargs)
            dispatch_status = str(ops_result.get("dispatch_status") or "accepted")
            failure_reason = ops_result.get("failure_reason")
        else:
            agent_name = TASK_AGENT_MAP[schedule.task_name]
            report_type = kwargs.get("report_type")
            period_key = kwargs.get("period_key")
            run_type = kwargs.get("run_type")
            if run_type and not report_type:
                report_type = run_type
            command = await publish_run_command(
                agent_name=agent_name,
                trigger_type=trigger_type,
                schedule_key=schedule.schedule_key,
                requested_by=requested_by,
                scheduled_for=scheduled_for.isoformat() if scheduled_for else None,
                report_type=report_type,
                run_type=run_type,
                period_key=period_key,
                force_send=kwargs.get("force_send"),
            )
            command_id = command.get("command_id")
            run_id = command.get("run_id")
    except Exception as exc:
        dispatch_status = "failed"
        failure_reason = str(exc)
        raise
    finally:
        await _log_dispatch_to_run_ledger(
            {
                "schedule_key": schedule.schedule_key,
                "task_name": schedule.task_name,
                "agent_name": TASK_AGENT_MAP.get(schedule.task_name),
                "trigger_type": trigger_type,
                "command_id": command_id,
                "run_id": run_id,
                "scheduled_for_at": scheduled_for.isoformat() if scheduled_for else None,
                "dispatched_at": dispatched_at.isoformat(),
                "dispatch_status": dispatch_status,
                "failure_reason": failure_reason,
                "task_kwargs": kwargs,
                "next_run_at": next_run_at.isoformat() if next_run_at else None,
            }
        )

    DISPATCH_TOTAL.labels(
        schedule_key=schedule.schedule_key,
        task_name=schedule.task_name,
        status=dispatch_status,
    ).inc()
    return {
        "accepted": dispatch_status == "accepted",
        "schedule_key": schedule.schedule_key,
        "task_name": schedule.task_name,
        "dispatch_status": dispatch_status,
        "command_id": command_id,
        "run_id": run_id,
        "failure_reason": failure_reason,
    }


async def _dispatch_ops_task(task_name: str, kwargs: dict) -> dict[str, Any]:
    if task_name == "ops.email_validation.run":
        if not settings.EMAIL_VALIDATION_ENABLED:
            logger.info("ops_task_skipped", task_name=task_name, reason="email_validation_disabled")
            return {
                "dispatch_status": "skipped",
                "failure_reason": "email_validation_disabled",
            }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.GATEWAY_SERVICE_URL.rstrip('/')}/internal/ops/email-validation/run",
                params={
                    "window": kwargs.get("window", "daily"),
                    "force": kwargs.get("force"),
                },
                headers={"X-Internal-Api-Key": settings.INTERNAL_API_KEY},
            )
        response.raise_for_status()
        logger.info("ops_task_dispatched", task_name=task_name, payload=response.json())
        return {"dispatch_status": "accepted"}
    raise ValueError(f"Unsupported ops task: {task_name}")


DISPATCH_JITTER_MAX_SECONDS = 30


async def _scheduler_loop(state: dict, stop_event: asyncio.Event):
    loop_interval = int(state.get("loop_interval_seconds") or 10)
    while not stop_event.is_set():
        now = datetime.now(timezone.utc)
        state["last_tick_at"] = now
        for schedule in state["schedules"]:
            if not schedule.enabled:
                state["next_seconds"][schedule.schedule_key] = None
                state["next_run_at"][schedule.schedule_key] = None
                continue

            due, next_in = schedule.cron.is_due(schedule.last_checked)
            next_seconds = float(next_in)
            next_run_at = now + timedelta(seconds=next_seconds)
            state["next_seconds"][schedule.schedule_key] = next_seconds
            state["next_run_at"][schedule.schedule_key] = next_run_at
            if due:
                agent_name = TASK_AGENT_MAP.get(schedule.task_name)
                # Overlap guard: skip if agent already has an inflight dispatch
                if agent_name and agent_name in state.get("inflight", {}):
                    inflight_at = state["inflight"][agent_name]
                    # Allow re-dispatch after a generous TTL (15 min) to handle stuck dispatches
                    if (now - inflight_at).total_seconds() < 900:
                        logger.info(
                            "schedule_skipped_overlap",
                            schedule_key=schedule.schedule_key,
                            agent_name=agent_name,
                            inflight_since=inflight_at.isoformat(),
                        )
                        schedule.last_checked = now
                        continue
                try:
                    # Jitter to prevent thundering herd
                    jitter = random.uniform(0, DISPATCH_JITTER_MAX_SECONDS)  # noqa: S311
                    await asyncio.sleep(jitter)
                    if agent_name:
                        state.setdefault("inflight", {})[agent_name] = datetime.now(timezone.utc)
                    await _dispatch(
                        schedule,
                        trigger_type="scheduled",
                        requested_by="scheduler",
                        scheduled_for=now,
                        next_run_at=next_run_at,
                    )
                    logger.info("schedule_dispatched", schedule_key=schedule.schedule_key, task_name=schedule.task_name)
                except Exception as e:
                    logger.exception("schedule_dispatch_failed", schedule_key=schedule.schedule_key, error=str(e))
                finally:
                    # Clear inflight after dispatch attempt completes
                    if agent_name:
                        state.get("inflight", {}).pop(agent_name, None)
            schedule.last_checked = now
        await asyncio.sleep(loop_interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    state = {
        "schedules": _load_schedules(),
        "next_seconds": {},
        "next_run_at": {},
        "inflight": {},
        "last_tick_at": None,
        "loop_interval_seconds": 10,
    }

    now_utc = datetime.now(timezone.utc)
    for schedule in state["schedules"]:
        next_run_at, next_seconds = _estimate_next_run_utc(schedule, now_utc)
        state["next_seconds"][schedule.schedule_key] = next_seconds
        state["next_run_at"][schedule.schedule_key] = next_run_at

    app.state.scheduler_state = state  # type: ignore[attr-defined]
    stop_event = asyncio.Event()
    task = asyncio.create_task(_scheduler_loop(state, stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Scheduler Service", lifespan=lifespan)
setup_metrics(app, "scheduler")
DISPATCH_TOTAL = Counter(
    "scheduler_dispatch_total",
    "Total dispatched schedule commands by schedule key and task name.",
    labelnames=("schedule_key", "task_name", "status"),
)


@app.get("/internal/health")
async def health():
    return {
        "status": "ok",
        "service": "scheduler",
        "schedules_loaded": len(app.state.scheduler_state["schedules"]),
    }


@app.get("/internal/state")
async def internal_state(_auth: None = Depends(require_internal_api_key)):
    return {
        "status": "ok",
        "service": "scheduler",
        "last_tick_at": (
            app.state.scheduler_state["last_tick_at"].isoformat()
            if app.state.scheduler_state.get("last_tick_at")
            else None
        ),
        "loop_interval_seconds": int(app.state.scheduler_state.get("loop_interval_seconds") or 10),
        "schedules_loaded": len(app.state.scheduler_state["schedules"]),
    }


@app.get("/internal/schedules")
async def schedules(_auth: None = Depends(require_internal_api_key)):
    return {
        "items": [
            {
                "schedule_key": s.schedule_key,
                "task_name": s.task_name,
                "timezone": s.timezone,
                "eat_cron": s.eat_cron,
                "utc_cron": s.utc_cron,
                "notes": s.notes,
                "task_kwargs": s.task_kwargs,
                "enabled": s.enabled,
                "next_seconds": app.state.scheduler_state["next_seconds"].get(s.schedule_key),
                "next_run_at_utc": (
                    app.state.scheduler_state["next_run_at"].get(s.schedule_key).isoformat()
                    if app.state.scheduler_state["next_run_at"].get(s.schedule_key)
                    else None
                ),
                "next_run_at_eat": _fmt_eat(app.state.scheduler_state["next_run_at"].get(s.schedule_key)),
            }
            for s in app.state.scheduler_state["schedules"]
        ]
    }


@app.post("/internal/dispatch/{schedule_key}")
async def dispatch(schedule_key: str, _auth: None = Depends(require_internal_api_key)):
    schedule = next((s for s in app.state.scheduler_state["schedules"] if s.schedule_key == schedule_key), None)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Unknown schedule key")

    now_utc = datetime.now(timezone.utc)
    result = await _dispatch(
        schedule,
        trigger_type="manual",
        requested_by="operator",
        scheduled_for=now_utc,
        next_run_at=app.state.scheduler_state["next_run_at"].get(schedule.schedule_key),
    )
    return result
