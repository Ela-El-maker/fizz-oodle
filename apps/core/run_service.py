from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.events import publish_run_event
from apps.core.logger import get_logger
from apps.core.models import AgentRun

logger = get_logger(__name__)
settings = get_settings()

RUN_STATUSES = {"running", "success", "partial", "fail"}
TERMINAL_STATUSES = {"success", "partial", "fail"}
_RUN_CACHE: dict[str, dict] = {}


def _coerce_status(status: str) -> str:
    s = status.strip().lower()
    if s == "started":
        s = "running"
    if s == "unknown":
        s = "fail"
    if s not in RUN_STATUSES:
        raise ValueError(f"Invalid run status: {status}")
    return s


async def start_run(agent_name: str, run_id: str | UUID | None = None, metrics: dict | None = None) -> str:
    rid = UUID(str(run_id)) if run_id else uuid4()
    started_at_dt = datetime.now(timezone.utc)
    started_at = started_at_dt.isoformat()
    run_metrics = metrics or {}

    if settings.RUN_DB_WRITE_ENABLED:
        try:
            async with get_session() as session:
                existing = await session.execute(select(AgentRun).where(AgentRun.run_id == rid))
                run = existing.scalar_one_or_none()

                if run is None:
                    run = AgentRun(
                        run_id=rid,
                        agent_name=agent_name,
                        started_at=started_at_dt,
                        status="running",
                        records_processed=0,
                        records_new=0,
                        errors_count=0,
                        metrics=run_metrics,
                        _legacy_outcome="running",
                        _legacy_metadata=run_metrics,
                    )
                    session.add(run)
                else:
                    run.agent_name = agent_name
                    run.status = "running"
                    run._legacy_outcome = "running"
                    run.started_at = run.started_at or started_at_dt
                    if run_metrics:
                        merged = dict(run.metrics or {})
                        merged.update(run_metrics)
                        run.metrics = merged
                        run._legacy_metadata = merged

                await session.commit()
        except SQLAlchemyError as e:
            logger.warning("run_db_start_skipped", run_id=str(rid), error=str(e))

    _RUN_CACHE[str(rid)] = {
        "agent_name": agent_name,
        "started_at": started_at,
        "metrics": run_metrics,
    }
    logger.info("run_started", run_id=str(rid), agent_name=agent_name, status="running")
    try:
        await publish_run_event(
            run_id=str(rid),
            agent_name=agent_name,
            status="running",
            started_at=started_at,
            finished_at=None,
            metrics=run_metrics,
            error_message=None,
            records_processed=0,
            records_new=0,
            errors_count=0,
        )
    except Exception as e:
        logger.warning("run_event_publish_failed", run_id=str(rid), stage="start", error=str(e))
    return str(rid)


async def finish_run(
    run_id: str | UUID,
    status: str,
    metrics: dict | None = None,
    error_message: str | None = None,
    records_processed: int | None = None,
    records_new: int | None = None,
    errors_count: int | None = None,
) -> None:
    rid = UUID(str(run_id))
    run_key = str(rid)
    normalized_status = _coerce_status(status)
    if normalized_status not in TERMINAL_STATUSES:
        raise ValueError("finish_run must use terminal status")

    cache_row = _RUN_CACHE.get(run_key, {})
    finished_at_dt = datetime.now(timezone.utc)
    finished_at = finished_at_dt.isoformat()
    run_agent_name = str(cache_row.get("agent_name") or "unknown")
    run_started_at = cache_row.get("started_at")
    run_metrics = metrics if metrics is not None else dict(cache_row.get("metrics") or {})
    run_records_processed = records_processed or 0
    run_records_new = records_new or 0
    run_errors_count = errors_count if errors_count is not None else (1 if normalized_status == "fail" else 0)

    if settings.RUN_DB_WRITE_ENABLED:
        try:
            async with get_session() as session:
                run = (await session.execute(select(AgentRun).where(AgentRun.run_id == rid))).scalar_one_or_none()
                if run is None:
                    run = AgentRun(
                        run_id=rid,
                        agent_name=run_agent_name,
                        started_at=datetime.fromisoformat(run_started_at) if run_started_at else finished_at_dt,
                        status="running",
                        records_processed=0,
                        records_new=0,
                        errors_count=0,
                        metrics=dict(cache_row.get("metrics") or {}),
                        _legacy_outcome="running",
                        _legacy_metadata=dict(cache_row.get("metrics") or {}),
                    )
                    session.add(run)
                    await session.flush()

                run.status = normalized_status
                run._legacy_outcome = normalized_status
                run.finished_at = finished_at_dt

                if metrics is not None:
                    run.metrics = metrics
                    run._legacy_metadata = metrics

                if error_message is not None:
                    run.error_message = error_message

                if records_processed is not None:
                    run.records_processed = records_processed

                if records_new is not None:
                    run.records_new = records_new

                if errors_count is not None:
                    run.errors_count = errors_count

                await session.commit()
                run_agent_name = run.agent_name
                run_started_at = run.started_at.isoformat() if run.started_at else run_started_at
                run_metrics = run.metrics or run_metrics
                run_records_processed = run.records_processed or run_records_processed
                run_records_new = run.records_new or run_records_new
                run_errors_count = run.errors_count if run.errors_count is not None else run_errors_count
        except SQLAlchemyError as e:
            logger.warning("run_db_finish_skipped", run_id=str(rid), error=str(e))

    logger.info(
        "run_finished",
        run_id=str(rid),
        agent_name=run_agent_name,
        status=normalized_status,
        records_processed=run_records_processed,
        records_new=run_records_new,
        errors_count=run_errors_count,
    )
    try:
        await publish_run_event(
            run_id=str(rid),
            agent_name=run_agent_name,
            status=normalized_status,
            started_at=run_started_at,
            finished_at=finished_at,
            metrics=run_metrics or {},
            error_message=error_message,
            records_processed=run_records_processed,
            records_new=run_records_new,
            errors_count=run_errors_count,
        )
    except Exception as e:
        logger.warning("run_event_publish_failed", run_id=str(rid), stage="finish", error=str(e))
    finally:
        _RUN_CACHE.pop(run_key, None)


async def fail_run(
    run_id: str | UUID,
    error_message: str,
    metrics: dict | None = None,
    records_processed: int | None = None,
    records_new: int | None = None,
    errors_count: int | None = None,
) -> None:
    await finish_run(
        run_id=run_id,
        status="fail",
        metrics=metrics,
        error_message=error_message,
        records_processed=records_processed,
        records_new=records_new,
        errors_count=errors_count if errors_count is not None else 1,
    )

    logger.error("run_failed", run_id=str(run_id), error=error_message)
