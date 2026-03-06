from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.models import SourceHealth

_SOURCE_HEALTH_AVAILABILITY_KEY = "_source_health_table_available"


def _roll_24h_counters(
    previous: dict | None,
    *,
    now_utc: datetime,
    success_inc: int = 0,
    failure_inc: int = 0,
    blocked_inc: int = 0,
) -> dict:
    metrics = dict(previous or {})
    window_started_at = metrics.get("window_started_at")
    reset = True
    if isinstance(window_started_at, str):
        try:
            started = datetime.fromisoformat(window_started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            reset = (now_utc - started) >= timedelta(hours=24)
        except Exception:
            reset = True

    if reset:
        metrics["window_started_at"] = now_utc.isoformat()
        metrics["success_count_24h"] = 0
        metrics["failure_count_24h"] = 0
        metrics["blocked_count_24h"] = 0

    metrics["success_count_24h"] = int(metrics.get("success_count_24h") or 0) + max(0, success_inc)
    metrics["failure_count_24h"] = int(metrics.get("failure_count_24h") or 0) + max(0, failure_inc)
    metrics["blocked_count_24h"] = int(metrics.get("blocked_count_24h") or 0) + max(0, blocked_inc)
    return metrics


async def get_source_health(session: AsyncSession, source_id: str) -> SourceHealth | None:
    available = await _source_health_table_available(session)
    if not available:
        return None
    try:
        return (await session.execute(select(SourceHealth).where(SourceHealth.source_id == source_id))).scalar_one_or_none()
    except SQLAlchemyError:
        # Backward-compat path for environments where source_health table has not been migrated yet.
        session.info[_SOURCE_HEALTH_AVAILABILITY_KEY] = False
        try:
            await session.rollback()
        except Exception:
            pass
        return None


async def _source_health_table_available(session: AsyncSession) -> bool:
    cached = session.info.get(_SOURCE_HEALTH_AVAILABILITY_KEY)
    if cached is not None:
        return bool(cached)
    try:
        await session.execute(select(SourceHealth.source_id).limit(1))
        session.info[_SOURCE_HEALTH_AVAILABILITY_KEY] = True
        return True
    except SQLAlchemyError:
        session.info[_SOURCE_HEALTH_AVAILABILITY_KEY] = False
        try:
            await session.rollback()
        except Exception:
            pass
        return False


async def source_can_run(
    session: AsyncSession,
    source_id: str,
    breaker_enabled: bool,
    now_utc: datetime,
) -> bool:
    if not breaker_enabled:
        return True
    row = await get_source_health(session, source_id)
    if row is None:
        return True
    if row.breaker_state != "open":
        return True
    if row.cooldown_until is None:
        return False
    cooldown = row.cooldown_until
    if cooldown.tzinfo is None:
        cooldown = cooldown.replace(tzinfo=timezone.utc)
    else:
        cooldown = cooldown.astimezone(timezone.utc)
    return cooldown <= now_utc


async def mark_source_success(session: AsyncSession, source_id: str, metrics: dict, now_utc: datetime) -> None:
    if not await _source_health_table_available(session):
        return
    try:
        row = await get_source_health(session, source_id)
        if row is None:
            row = SourceHealth(source_id=source_id)
            session.add(row)

        row.last_success_at = now_utc
        row.consecutive_failures = 0
        row.breaker_state = "closed"
        row.cooldown_until = None
        merged = _roll_24h_counters(
            row.last_metrics if isinstance(row.last_metrics, dict) else {},
            now_utc=now_utc,
            success_inc=1,
        )
        merged.update(metrics or {})
        merged["last_error_type"] = None
        row.last_metrics = merged
    except SQLAlchemyError:
        # Non-blocking: health telemetry should never break the briefing pipeline.
        try:
            await session.rollback()
        except Exception:
            pass
        return


async def mark_source_failure(
    session: AsyncSession,
    source_id: str,
    *,
    error: str,
    error_type: str,
    now_utc: datetime,
    fail_threshold: int,
    cooldown_minutes: int,
) -> None:
    if not await _source_health_table_available(session):
        return
    try:
        row = await get_source_health(session, source_id)
        if row is None:
            row = SourceHealth(source_id=source_id)
            session.add(row)

        row.last_failure_at = now_utc
        row.consecutive_failures = int(row.consecutive_failures or 0) + 1
        merged = _roll_24h_counters(
            row.last_metrics if isinstance(row.last_metrics, dict) else {},
            now_utc=now_utc,
            failure_inc=1,
            blocked_inc=1 if error_type == "blocked" else 0,
        )
        merged.update({"error": error, "error_type": error_type, "last_error_type": error_type})
        row.last_metrics = merged

        if row.consecutive_failures >= fail_threshold:
            row.breaker_state = "open"
            row.cooldown_until = now_utc + timedelta(minutes=cooldown_minutes)
        else:
            row.breaker_state = "closed"
    except SQLAlchemyError:
        # Non-blocking: health telemetry should never break the briefing pipeline.
        try:
            await session.rollback()
        except Exception:
            pass
        return
