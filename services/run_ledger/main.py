from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import os
from typing import Any
from uuid import UUID
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
try:
    from prometheus_client import Counter, Gauge
except Exception:  # pragma: no cover - fallback for minimal dev envs
    class _NoOpMetric:  # noqa: D401
        def labels(self, **_kwargs):
            return self

        def inc(self, *_args, **_kwargs):
            return None

        def set(self, *_args, **_kwargs):
            return None

    def Counter(*_args, **_kwargs):  # type: ignore[misc]
        return _NoOpMetric()

    def Gauge(*_args, **_kwargs):  # type: ignore[misc]
        return _NoOpMetric()
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select, update

from apps.core.autonomy_policy import get_latest_autonomy_state
from apps.api.routers.auth import require_api_key
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.events import ack_stream_group, iter_stream_group
from apps.core.events import publish_ops_healing_applied
from apps.core.events import publish_run_command
from apps.core.events import publish_run_event
from apps.core.healing_engine import list_incidents, record_healing_incident
from apps.core.learning_engine import get_latest_learning_summary
from apps.core.logger import configure_logging, get_logger
from apps.core.models import (
    AgentRun,
    EmailValidationRun,
    EmailValidationStep,
    RunCommand,
    SchedulerDispatch,
    SchedulerTimelineEvent,
)
from apps.core.scheduler_monitor import (
    build_scheduler_snapshot,
    get_scheduler_active,
    get_scheduler_email,
    get_scheduler_events,
    get_scheduler_heatmap,
    get_scheduler_history,
    get_scheduler_impact,
    get_scheduler_pipeline,
    get_scheduler_status,
    get_scheduler_upcoming,
)
from apps.core.self_mod_engine import (
    apply_self_mod_proposal,
    generate_self_mod_proposals,
    get_self_mod_state,
    list_self_mod_proposals,
)
from services.common.security import require_internal_api_key
from services.common.metrics import setup_metrics

configure_logging()
logger = get_logger(__name__)
settings = get_settings()
RUN_EVENTS_TOTAL = Counter(
    "run_events_total",
    "Total run events consumed by run-ledger.",
    labelnames=("agent_name", "status"),
)
STALE_RUNS_RECONCILED_TOTAL = Counter(
    "stale_runs_reconciled_total",
    "Total stale running runs reconciled by run-ledger.",
    labelnames=("agent_name",),
)
STALE_RECONCILER_LAST_TS = Gauge(
    "stale_reconciler_last_run_timestamp",
    "UNIX timestamp of last stale run reconciliation sweep.",
)
EMAIL_VALIDATION_RUNS_TOTAL = Counter(
    "email_validation_runs_total",
    "Total email validation runs by window and final status.",
    labelnames=("window", "status"),
)
EMAIL_VALIDATION_STEP_TOTAL = Counter(
    "email_validation_step_total",
    "Total email validation steps by window, agent and status.",
    labelnames=("window", "agent", "status"),
)
EMAIL_VALIDATION_LAST_SUCCESS_TS = Gauge(
    "email_validation_last_success_timestamp",
    "UNIX timestamp of last successful email validation run per window.",
    labelnames=("window",),
)


class EmailValidationStepUpsert(BaseModel):
    agent_name: str
    run_id: str | None = None
    status: str
    email_sent: bool = False
    email_error: str | None = None
    metrics_json: dict = Field(default_factory=dict)


class EmailValidationFinishPayload(BaseModel):
    status: str
    summary_json: dict = Field(default_factory=dict)


class SchedulerDispatchLogPayload(BaseModel):
    schedule_key: str
    task_name: str
    agent_name: str | None = None
    trigger_type: str = "scheduled"
    command_id: str | None = None
    run_id: str | None = None
    scheduled_for_at: str | None = None
    dispatched_at: str | None = None
    dispatch_status: str = "accepted"
    failure_reason: str | None = None
    task_kwargs: dict = Field(default_factory=dict)
    next_run_at: str | None = None


def _none_like(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in {"", "none", "null"})


def _parse_optional_dt(value: object) -> datetime | None:
    if _none_like(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"Invalid datetime value: {value!r}")


def _parse_optional_uuid(value: object) -> UUID | None:
    if _none_like(value):
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError(f"Invalid UUID value: {value!r}")


async def _consume_run_commands(stop_event: asyncio.Event):
    stream = settings.REDIS_STREAM_COMMANDS
    group = "commands:ledger"
    consumer = f"run-ledger:{os.getpid()}:{uuid4().hex[:8]}:commands"
    logger.info("run_command_listener_started", stream=stream, group=group, consumer=consumer)
    backoff = 1.0
    while not stop_event.is_set():
        try:
            async for _stream_name, msg_id, payload in iter_stream_group(stream, group=group, consumer=consumer, block_ms=3000, count=100):
                if stop_event.is_set():
                    return
                backoff = 1.0
                if msg_id is None:
                    await asyncio.sleep(0.1)
                    continue
                if payload is None:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    await asyncio.sleep(0.1)
                    continue
                if payload.get("schema") != "RunCommandV1":
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    continue

                try:
                    command_id = UUID(str(payload["command_id"]))
                    run_id = _parse_optional_uuid(payload.get("run_id")) or uuid4()
                    requested_at = _parse_optional_dt(payload.get("requested_at")) or datetime.now(timezone.utc)
                    async with get_session() as session:
                        row = (
                            await session.execute(select(RunCommand).where(RunCommand.command_id == command_id))
                        ).scalar_one_or_none()
                        if row is None:
                            row = RunCommand(
                                command_id=command_id,
                                run_id=run_id,
                                agent_name=str(payload.get("agent_name") or "unknown"),
                                trigger_type=str(payload.get("trigger_type") or "unknown"),
                                schedule_key=payload.get("schedule_key"),
                                requested_by=payload.get("requested_by"),
                                requested_at=requested_at,
                                report_type=payload.get("report_type"),
                                run_type=payload.get("run_type"),
                                period_key=payload.get("period_key"),
                                force_send=payload.get("force_send"),
                                email_recipients_override=payload.get("email_recipients_override"),
                                payload=payload,
                                lifecycle_status="queued",
                                updated_at=datetime.now(timezone.utc),
                            )
                            session.add(row)
                        else:
                            row.run_id = run_id
                            row.agent_name = str(payload.get("agent_name") or row.agent_name)
                            row.trigger_type = str(payload.get("trigger_type") or row.trigger_type or "unknown")
                            row.schedule_key = payload.get("schedule_key")
                            row.requested_by = payload.get("requested_by")
                            row.requested_at = requested_at
                            row.report_type = payload.get("report_type")
                            row.run_type = payload.get("run_type")
                            row.period_key = payload.get("period_key")
                            row.force_send = payload.get("force_send")
                            row.email_recipients_override = payload.get("email_recipients_override")
                            row.payload = payload
                            row.lifecycle_status = "queued"
                            row.updated_at = datetime.now(timezone.utc)

                        timeline = SchedulerTimelineEvent(
                            event_time=requested_at,
                            event_type="run_command_queued",
                            severity="info",
                            source="scheduler" if payload.get("requested_by") == "scheduler" else "gateway",
                            agent_name=str(payload.get("agent_name") or "unknown"),
                            run_id=run_id,
                            schedule_key=payload.get("schedule_key"),
                            message=f"Run command queued for {payload.get('agent_name')}",
                            details={"trigger_type": payload.get("trigger_type"), "requested_by": payload.get("requested_by")},
                        )
                        session.add(timeline)
                        await session.commit()
                except Exception as e:
                    logger.exception("run_command_consume_failed", error=str(e), payload=payload)
                finally:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("run_command_listener_reconnecting", error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)


async def _consume_run_events(stop_event: asyncio.Event):
    stream = settings.REDIS_STREAM_RUN_EVENTS
    group = "runs:ledger"
    consumer = f"run-ledger:{os.getpid()}:{uuid4().hex[:8]}"
    logger.info("run_ledger_listener_started", stream=stream, group=group, consumer=consumer)
    backoff = 1.0
    while not stop_event.is_set():
        try:
            async for _stream_name, msg_id, payload in iter_stream_group(stream, group=group, consumer=consumer, block_ms=3000, count=100):
                if stop_event.is_set():
                    return
                backoff = 1.0
                if msg_id is None:
                    await asyncio.sleep(0.1)
                    continue
                if payload is None:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    await asyncio.sleep(0.1)
                    continue
                if payload.get("schema") != "RunEventV1":
                    await ack_stream_group(stream, group=group, message_id=msg_id)
                    continue
                try:
                    run_id = UUID(str(payload["run_id"]))
                    async with get_session() as session:
                        row = (await session.execute(select(AgentRun).where(AgentRun.run_id == run_id))).scalar_one_or_none()
                        started_at = _parse_optional_dt(payload.get("started_at"))
                        finished_at = _parse_optional_dt(payload.get("finished_at"))
                        status = str(payload.get("status") or "running")
                        if row is None:
                            row = AgentRun(
                                run_id=run_id,
                                agent_name=str(payload.get("agent_name") or "unknown"),
                                status=status,
                                started_at=started_at or datetime.now(timezone.utc),
                                finished_at=finished_at,
                                metrics=payload.get("metrics") or {},
                                error_message=payload.get("error_message"),
                                records_processed=int(payload.get("records_processed") or 0),
                                records_new=int(payload.get("records_new") or 0),
                                errors_count=int(payload.get("errors_count") or 0),
                                _legacy_outcome=status,
                                _legacy_metadata=payload.get("metrics") or {},
                            )
                            session.add(row)
                        else:
                            row.agent_name = str(payload.get("agent_name") or row.agent_name)
                            row.status = status
                            row._legacy_outcome = status
                            if started_at:
                                row.started_at = started_at
                            if finished_at:
                                row.finished_at = finished_at
                            row.metrics = payload.get("metrics") or {}
                            row._legacy_metadata = row.metrics
                            row.error_message = payload.get("error_message")
                            if payload.get("records_processed") is not None:
                                row.records_processed = int(payload.get("records_processed") or 0)
                            if payload.get("records_new") is not None:
                                row.records_new = int(payload.get("records_new") or 0)
                            if payload.get("errors_count") is not None:
                                row.errors_count = int(payload.get("errors_count") or 0)

                        cmd = (
                            await session.execute(
                                select(RunCommand)
                                .where(RunCommand.run_id == run_id)
                                .order_by(desc(RunCommand.requested_at))
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if cmd is not None:
                            if status == "running":
                                cmd.lifecycle_status = "started"
                            elif status in {"success", "partial", "fail"}:
                                cmd.lifecycle_status = "finished"
                            cmd.updated_at = datetime.now(timezone.utc)

                        timeline = SchedulerTimelineEvent(
                            event_time=finished_at or started_at or datetime.now(timezone.utc),
                            event_type=f"run_{status}",
                            severity="error" if status == "fail" else "warn" if status == "partial" else "info",
                            source="run_ledger",
                            agent_name=row.agent_name,
                            run_id=row.run_id,
                            schedule_key=cmd.schedule_key if cmd is not None else None,
                            message=f"Run {status} for {row.agent_name}",
                            details={
                                "status_reason": (row.metrics or {}).get("status_reason") or row.error_message,
                                "records_processed": int(row.records_processed or 0),
                                "records_new": int(row.records_new or 0),
                                "errors_count": int(row.errors_count or 0),
                            },
                        )
                        session.add(timeline)
                        await session.commit()
                        RUN_EVENTS_TOTAL.labels(agent_name=row.agent_name, status=row.status).inc()
                except Exception as e:
                    logger.exception("run_ledger_consume_failed", error=str(e), payload=payload)
                finally:
                    await ack_stream_group(stream, group=group, message_id=msg_id)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("run_event_listener_reconnecting", error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)


def _agent_stale_ttl_minutes(agent_name: str) -> int:
    mapping = {
        "announcements": settings.ANNOUNCEMENTS_STALE_RUN_TTL_MINUTES,
        "briefing": settings.BRIEFING_STALE_RUN_TTL_MINUTES,
        "sentiment": settings.SENTIMENT_STALE_RUN_TTL_MINUTES,
        "analyst": settings.ANALYST_STALE_RUN_TTL_MINUTES,
        "archivist": settings.ARCHIVIST_STALE_RUN_TTL_MINUTES,
        "narrator": settings.NARRATOR_STALE_RUN_TTL_MINUTES,
    }
    if agent_name not in mapping:
        return 0
    return max(1, int(mapping[agent_name]))


def _is_stale_running_run(row: AgentRun, now_utc: datetime) -> bool:
    if row.status != "running" or row.started_at is None:
        return False
    ttl_minutes = _agent_stale_ttl_minutes(row.agent_name)
    if ttl_minutes <= 0:
        return False
    return row.started_at < (now_utc - timedelta(minutes=ttl_minutes))


async def _reconcile_stale_runs_once() -> int:
    now_utc = datetime.now(timezone.utc)
    stale_rows: list[AgentRun] = []
    async with get_session() as session:
        candidates = (
            await session.execute(select(AgentRun).where(AgentRun.status == "running"))
        ).scalars().all()

        for row in candidates:
            if _is_stale_running_run(row, now_utc):
                stale_rows.append(row)

        if stale_rows:
            for row in stale_rows:
                metrics = dict(row.metrics or {})
                metrics["stale_reconciled"] = True
                metrics["stale_reconciled_at"] = now_utc.isoformat()
                await session.execute(
                    update(AgentRun)
                    .where(AgentRun.run_id == row.run_id, AgentRun.status == "running")
                    .values(
                        status="fail",
                        _legacy_outcome="fail",
                        finished_at=now_utc,
                        error_message="stale_run_timeout",
                        metrics=metrics,
                        _legacy_metadata=metrics,
                    )
                )
            await session.commit()

    for row in stale_rows:
        STALE_RUNS_RECONCILED_TOTAL.labels(agent_name=row.agent_name).inc()
        try:
            async with get_session() as incident_session:
                incident_row = await record_healing_incident(
                    incident_session,
                    component=f"agent:{row.agent_name}",
                    failure_type="stale_run_timeout",
                    action="mark_run_failed",
                    result="applied",
                    duration_ms=0,
                    auto_applied=True,
                    escalated=False,
                    details={"run_id": str(row.run_id)},
                    error_message="stale_run_timeout",
                )
            try:
                await publish_ops_healing_applied(
                    {
                        "incident_id": str(incident_row.incident_id),
                        "component": incident_row.component,
                        "failure_type": incident_row.failure_type,
                        "action": incident_row.action,
                        "result": incident_row.result,
                        "auto_applied": bool(incident_row.auto_applied),
                        "escalated": bool(incident_row.escalated),
                        "occurred_at": now_utc.isoformat(),
                    }
                )
            except Exception as exc:  # noqa: PERF203
                logger.warning("healing_event_publish_failed", incident_id=str(incident_row.incident_id), error=str(exc))
        except Exception as exc:  # noqa: PERF203
            logger.warning("stale_run_incident_record_failed", run_id=str(row.run_id), error=str(exc))
        try:
            await publish_run_event(
                run_id=str(row.run_id),
                agent_name=row.agent_name,
                status="fail",
                started_at=row.started_at.isoformat() if row.started_at else None,
                finished_at=now_utc.isoformat(),
                metrics={**(row.metrics or {}), "stale_reconciled": True},
                error_message="stale_run_timeout",
            )
        except Exception as exc:  # noqa: PERF203
            logger.warning("stale_run_event_publish_failed", run_id=str(row.run_id), error=str(exc))

    STALE_RECONCILER_LAST_TS.set(now_utc.timestamp())
    return len(stale_rows)


async def _stale_reconciler_loop(stop_event: asyncio.Event):
    interval = max(10, int(settings.STALE_RUN_RECONCILER_INTERVAL_SECONDS))
    while not stop_event.is_set():
        try:
            if settings.STALE_RUN_RECONCILER_ENABLED:
                reconciled = await _reconcile_stale_runs_once()
                if reconciled:
                    logger.info("stale_runs_reconciled", count=reconciled)
        except Exception as exc:  # noqa: PERF203
            logger.exception("stale_reconciler_failed", error=str(exc))
        await asyncio.sleep(interval)


async def _self_mod_loop(stop_event: asyncio.Event):
    interval = max(120, int(settings.SELF_MOD_RECOMPUTE_INTERVAL_SECONDS))
    while not stop_event.is_set():
        try:
            if settings.SELF_MOD_BACKGROUND_ENABLED:
                async with get_session() as session:
                    result = await generate_self_mod_proposals(session, refresh=True, auto_apply=True)
                if int(result.get("created") or 0) > 0 or int(result.get("applied") or 0) > 0:
                    logger.info(
                        "self_mod_cycle_applied",
                        created=int(result.get("created") or 0),
                        applied=int(result.get("applied") or 0),
                    )
        except Exception as exc:  # noqa: PERF203
            logger.exception("self_mod_loop_failed", error=str(exc))
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    task = asyncio.create_task(_consume_run_events(stop_event))
    command_task = asyncio.create_task(_consume_run_commands(stop_event))
    stale_task = asyncio.create_task(_stale_reconciler_loop(stop_event))
    self_mod_task = asyncio.create_task(_self_mod_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        command_task.cancel()
        stale_task.cancel()
        self_mod_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        with contextlib.suppress(asyncio.CancelledError):
            await command_task
        with contextlib.suppress(asyncio.CancelledError):
            await stale_task
        with contextlib.suppress(asyncio.CancelledError):
            await self_mod_task


app = FastAPI(title="Run Ledger Service", lifespan=lifespan)
setup_metrics(app, "run_ledger")


@app.get("/internal/health")
async def internal_health():
    return {"status": "ok", "service": "run-ledger"}


@app.post("/internal/scheduler/dispatch-log", dependencies=[Depends(require_internal_api_key)])
async def internal_scheduler_dispatch_log(payload: SchedulerDispatchLogPayload):
    dispatched_at = _parse_optional_dt(payload.dispatched_at) or datetime.now(timezone.utc)
    scheduled_for_at = _parse_optional_dt(payload.scheduled_for_at)
    next_run_at = _parse_optional_dt(payload.next_run_at)
    command_id = _parse_optional_uuid(payload.command_id)
    run_id = _parse_optional_uuid(payload.run_id)
    async with get_session() as session:
        row = SchedulerDispatch(
            schedule_key=payload.schedule_key,
            task_name=payload.task_name,
            agent_name=payload.agent_name,
            trigger_type=payload.trigger_type,
            command_id=command_id,
            run_id=run_id,
            scheduled_for_at=scheduled_for_at,
            dispatched_at=dispatched_at,
            dispatch_status=payload.dispatch_status,
            failure_reason=payload.failure_reason,
            task_kwargs=payload.task_kwargs or {},
            next_run_at=next_run_at,
        )
        session.add(row)
        timeline = SchedulerTimelineEvent(
            event_time=dispatched_at,
            event_type="scheduler_dispatch",
            severity="error" if payload.dispatch_status == "failed" else "warn" if payload.dispatch_status == "skipped" else "info",
            source="scheduler",
            agent_name=payload.agent_name,
            run_id=run_id,
            schedule_key=payload.schedule_key,
            message=f"Dispatch {payload.dispatch_status} for {payload.schedule_key}",
            details={
                "trigger_type": payload.trigger_type,
                "task_name": payload.task_name,
                "failure_reason": payload.failure_reason,
            },
        )
        session.add(timeline)
        await session.commit()
    return {"accepted": True}


async def _retry_run_by_id(run_id: UUID, *, requested_by: str) -> dict[str, Any]:
    async with get_session() as session:
        row = (
            await session.execute(select(AgentRun).where(AgentRun.run_id == run_id).limit(1))
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")

    new_run_id = str(uuid4())
    command = await publish_run_command(
        agent_name=row.agent_name,
        run_id=new_run_id,
        trigger_type="retry",
        requested_by=requested_by,
        report_type=(row.metrics or {}).get("report_type"),
        run_type=(row.metrics or {}).get("run_type"),
        period_key=(row.metrics or {}).get("period_key"),
        force_send=False,
    )

    async with get_session() as session:
        timeline = SchedulerTimelineEvent(
            event_time=datetime.now(timezone.utc),
            event_type="retry_requested",
            severity="warn",
            source="run_ledger",
            agent_name=row.agent_name,
            run_id=_parse_optional_uuid(command.get("run_id")),
            schedule_key=None,
            message=f"Retry queued for {row.agent_name}",
            details={"previous_run_id": str(run_id), "requested_by": requested_by},
        )
        session.add(timeline)
        await session.commit()

    return {
        "accepted": True,
        "previous_run_id": str(run_id),
        "run_id": command.get("run_id"),
        "command_id": command.get("command_id"),
        "agent_name": row.agent_name,
        "trigger_type": "retry",
    }


@app.post("/internal/scheduler/retry/{run_id}", dependencies=[Depends(require_internal_api_key)])
async def internal_scheduler_retry(run_id: str):
    try:
        parsed = UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid run_id") from exc
    return await _retry_run_by_id(parsed, requested_by="retry_engine")


@app.post("/scheduler/control/retry/{run_id}")
async def scheduler_control_retry(run_id: str, _auth: None = Depends(require_api_key)):
    try:
        parsed = UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid run_id") from exc
    return await _retry_run_by_id(parsed, requested_by="operator")


@app.get("/scheduler/monitor/status")
async def scheduler_monitor_status(_auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_status(session)


@app.get("/scheduler/monitor/active")
async def scheduler_monitor_active(_auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_active(session)


@app.get("/scheduler/monitor/upcoming")
async def scheduler_monitor_upcoming(hours: int = 24, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_upcoming(session, hours=hours)


@app.get("/scheduler/monitor/history")
async def scheduler_monitor_history(limit: int = 50, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_history(session, limit=limit)


@app.get("/scheduler/monitor/pipeline")
async def scheduler_monitor_pipeline(window_minutes: int = 120, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_pipeline(session, window_minutes=window_minutes)


@app.get("/scheduler/monitor/email")
async def scheduler_monitor_email(_auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_email(session)


@app.get("/scheduler/monitor/events")
async def scheduler_monitor_events(limit: int = 50, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_events(session, limit=limit)


@app.get("/scheduler/monitor/heatmap")
async def scheduler_monitor_heatmap(hours: int = 24, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_heatmap(session, hours=hours)


@app.get("/scheduler/monitor/impact")
async def scheduler_monitor_impact(failed_agent: str, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        return await get_scheduler_impact(session, failed_agent=failed_agent)


@app.get("/scheduler/monitor/snapshot")
async def scheduler_monitor_snapshot(
    hours: int = 24,
    events_limit: int = 50,
    failed_agent: str | None = None,
    _auth: None = Depends(require_api_key),
):
    async with get_session() as session:
        return await build_scheduler_snapshot(
            session,
            hours=hours,
            events_limit=events_limit,
            failed_agent=failed_agent,
        )


@app.get("/runs")
async def runs(agent_name: str | None = None, status: str | None = None, limit: int = 50, _auth: None = Depends(require_api_key)):
    safe_limit = max(1, min(limit, 200))
    async with get_session() as session:
        stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(safe_limit)
        if agent_name:
            stmt = stmt.where(AgentRun.agent_name == agent_name)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "items": [
            {
                "run_id": str(r.run_id),
                "agent_name": r.agent_name,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "metrics": r.metrics or {},
                "error_message": r.error_message,
                "records_processed": int(r.records_processed or 0),
                "records_new": int(r.records_new or 0),
                "errors_count": int(r.errors_count or 0),
                "status_reason": (r.metrics or {}).get("status_reason") or r.error_message,
                "is_stale_reconciled": bool((r.metrics or {}).get("stale_reconciled")),
            }
            for r in rows
        ]
    }


@app.get("/runs/latest/{agent_name}")
async def latest_run(agent_name: str, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        row = (
            await session.execute(
                select(AgentRun).where(AgentRun.agent_name == agent_name).order_by(AgentRun.started_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No runs")
    return {
        "run_id": str(row.run_id),
        "agent_name": row.agent_name,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "metrics": row.metrics or {},
        "error_message": row.error_message,
        "records_processed": int(row.records_processed or 0),
        "records_new": int(row.records_new or 0),
        "errors_count": int(row.errors_count or 0),
        "status_reason": (row.metrics or {}).get("status_reason") or row.error_message,
        "is_stale_reconciled": bool((row.metrics or {}).get("stale_reconciled")),
    }


def _period_key(window: str, provided: str | None) -> date:
    if provided:
        return date.fromisoformat(provided)
    today_eat = datetime.now(ZoneInfo("Africa/Nairobi")).date()
    if window == "weekly":
        return today_eat - timedelta(days=today_eat.weekday())
    return today_eat


@app.post("/internal/email-validation/start", dependencies=[Depends(require_internal_api_key)])
async def start_email_validation(
    window: str = "daily",
    period_key: str | None = None,
    force: bool = False,
):
    normalized = (window or "daily").strip().lower()
    if normalized not in {"daily", "weekly"}:
        raise HTTPException(status_code=400, detail="window must be daily|weekly")
    pk = _period_key(normalized, period_key)

    async with get_session() as session:
        existing = (
            await session.execute(
                select(EmailValidationRun)
                .where(EmailValidationRun.window == normalized, EmailValidationRun.period_key == pk)
                .limit(1)
            )
        ).scalar_one_or_none()

        if existing is not None and not force:
            return {
                "validation_run_id": str(existing.validation_run_id),
                "window": existing.window,
                "period_key": existing.period_key.isoformat(),
                "status": existing.status,
                "summary_json": existing.summary_json or {},
                "reused": True,
            }

        now_utc = datetime.now(timezone.utc)
        if existing is None:
            existing = EmailValidationRun(
                window=normalized,
                period_key=pk,
                status="running",
                started_at=now_utc,
                finished_at=None,
                summary_json={},
            )
            session.add(existing)
            await session.flush()
        else:
            await session.execute(
                delete(EmailValidationStep).where(EmailValidationStep.validation_run_id == existing.validation_run_id)
            )
            existing.status = "running"
            existing.started_at = now_utc
            existing.finished_at = None
            existing.summary_json = {}

        await session.commit()
        return {
            "validation_run_id": str(existing.validation_run_id),
            "window": existing.window,
            "period_key": existing.period_key.isoformat(),
            "status": existing.status,
            "summary_json": existing.summary_json or {},
            "reused": False,
        }


@app.post("/internal/email-validation/{validation_run_id}/step", dependencies=[Depends(require_internal_api_key)])
async def upsert_email_validation_step(validation_run_id: str, payload: EmailValidationStepUpsert):
    vid = UUID(validation_run_id)
    async with get_session() as session:
        run = (
            await session.execute(
                select(EmailValidationRun).where(EmailValidationRun.validation_run_id == vid).limit(1)
            )
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="validation run not found")

        row = (
            await session.execute(
                select(EmailValidationStep)
                .where(
                    EmailValidationStep.validation_run_id == vid,
                    EmailValidationStep.agent_name == payload.agent_name,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        now_utc = datetime.now(timezone.utc)
        try:
            parsed_run_id = UUID(payload.run_id) if payload.run_id else None
        except ValueError:
            parsed_run_id = None
        if row is None:
            row = EmailValidationStep(
                validation_run_id=vid,
                agent_name=payload.agent_name,
                run_id=parsed_run_id,
                status=payload.status,
                email_sent=payload.email_sent,
                email_error=payload.email_error,
                metrics_json=payload.metrics_json or {},
                created_at=now_utc,
                updated_at=now_utc,
            )
            session.add(row)
        else:
            row.run_id = parsed_run_id
            row.status = payload.status
            row.email_sent = payload.email_sent
            row.email_error = payload.email_error
            row.metrics_json = payload.metrics_json or {}
            row.updated_at = now_utc
        await session.commit()

    EMAIL_VALIDATION_STEP_TOTAL.labels(window=run.window, agent=payload.agent_name, status=payload.status).inc()
    return {"accepted": True}


@app.post("/internal/email-validation/{validation_run_id}/finish", dependencies=[Depends(require_internal_api_key)])
async def finish_email_validation(validation_run_id: str, payload: EmailValidationFinishPayload):
    vid = UUID(validation_run_id)
    async with get_session() as session:
        row = (
            await session.execute(
                select(EmailValidationRun).where(EmailValidationRun.validation_run_id == vid).limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="validation run not found")

        row.status = payload.status
        row.finished_at = datetime.now(timezone.utc)
        row.summary_json = payload.summary_json or {}
        await session.commit()

    EMAIL_VALIDATION_RUNS_TOTAL.labels(window=row.window, status=payload.status).inc()
    if payload.status == "success" and row.finished_at is not None:
        EMAIL_VALIDATION_LAST_SUCCESS_TS.labels(window=row.window).set(row.finished_at.timestamp())
    return {"accepted": True}


@app.get("/internal/email-validation/latest", dependencies=[Depends(require_internal_api_key)])
async def latest_email_validation(window: str | None = None):
    normalized = window.strip().lower() if window else None
    async with get_session() as session:
        stmt = select(EmailValidationRun).order_by(desc(EmailValidationRun.started_at)).limit(1)
        if normalized:
            stmt = (
                select(EmailValidationRun)
                .where(EmailValidationRun.window == normalized)
                .order_by(desc(EmailValidationRun.started_at))
                .limit(1)
            )
        run = (await session.execute(stmt)).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="no email validation runs")
        steps = (
            await session.execute(
                select(EmailValidationStep)
                .where(EmailValidationStep.validation_run_id == run.validation_run_id)
                .order_by(EmailValidationStep.agent_name.asc())
            )
        ).scalars().all()

    return {
        "item": {
            "validation_run_id": str(run.validation_run_id),
            "window": run.window,
            "period_key": run.period_key.isoformat(),
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "summary_json": run.summary_json or {},
            "steps": [
                {
                    "agent_name": s.agent_name,
                    "run_id": str(s.run_id) if s.run_id else None,
                    "status": s.status,
                    "email_sent": s.email_sent,
                    "email_error": s.email_error,
                    "metrics_json": s.metrics_json or {},
                }
                for s in steps
            ],
        }
    }


@app.get("/email-validation/latest")
async def public_latest_email_validation(window: str | None = None, _auth: None = Depends(require_api_key)):
    return await latest_email_validation(window=window)


@app.get("/system/autonomy/state")
async def system_autonomy_state(refresh: bool = False, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        item = await get_latest_autonomy_state(session, refresh=refresh)
    return {"item": item}


@app.get("/system/healing/incidents")
async def system_healing_incidents(limit: int = 50, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        items = await list_incidents(session, limit=limit)
    return {"items": items, "limit": max(1, min(limit, 200))}


@app.get("/system/learning/summary")
async def system_learning_summary(refresh: bool = False, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        item = await get_latest_learning_summary(session, refresh=refresh)
    return {"item": item}


@app.get("/system/self-mod/state")
async def system_self_mod_state(_auth: None = Depends(require_api_key)):
    async with get_session() as session:
        item = await get_self_mod_state(session)
    return {"item": item}


@app.get("/system/self-mod/proposals")
async def system_self_mod_proposals(status: str | None = None, limit: int = 50, _auth: None = Depends(require_api_key)):
    async with get_session() as session:
        items = await list_self_mod_proposals(session, status=status, limit=limit)
    return {"items": items, "limit": max(1, min(limit, 200))}


@app.post("/system/self-mod/generate")
async def system_self_mod_generate(
    refresh: bool = True,
    auto_apply: bool | None = None,
    _auth: None = Depends(require_api_key),
):
    async with get_session() as session:
        result = await generate_self_mod_proposals(session, refresh=refresh, auto_apply=auto_apply)
    return result


@app.post("/system/self-mod/apply/{proposal_id}")
async def system_self_mod_apply(
    proposal_id: str,
    auto_applied: bool = False,
    _auth: None = Depends(require_api_key),
):
    try:
        proposal_uuid = UUID(proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid proposal_id") from exc
    async with get_session() as session:
        try:
            result = await apply_self_mod_proposal(session, proposal_id=proposal_uuid, auto_applied=auto_applied)
        except ValueError as exc:
            if str(exc) == "proposal_not_found":
                raise HTTPException(status_code=404, detail="proposal not found") from exc
            if str(exc) == "proposal_not_auto_eligible":
                raise HTTPException(status_code=409, detail="proposal not auto eligible") from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
