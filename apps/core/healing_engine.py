from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.models import HealingIncident

FAILURE_TYPES = {
    "timeout",
    "dns_error",
    "connection_error",
    "rate_limited",
    "blocked",
    "parse_error",
    "db_error",
    "llm_error",
    "missing_key",
    "source_breaker_open",
    "stale_run_timeout",
    "unknown",
}

SAFE_ACTION_BY_FAILURE = {
    "timeout": "retry_with_backoff",
    "dns_error": "retry_with_backoff",
    "connection_error": "restart_worker_once",
    "rate_limited": "reduce_source_rps",
    "blocked": "disable_source_temporarily",
    "parse_error": "open_source_breaker",
    "db_error": "restart_worker_once",
    "llm_error": "switch_rule_only_mode",
    "missing_key": "skip_source",
    "source_breaker_open": "switch_to_fallback_source",
    "stale_run_timeout": "mark_run_failed",
    "unknown": "record_and_escalate",
}


def classify_failure(*, error_message: str | None = None, status_code: int | None = None) -> str:
    lowered = (error_message or "").strip().lower()
    if status_code == 429 or "rate limit" in lowered:
        return "rate_limited"
    if status_code == 403 or "forbidden" in lowered or "blocked" in lowered:
        return "blocked"
    if "timeout" in lowered:
        return "timeout"
    if "dns" in lowered or "name or service not known" in lowered:
        return "dns_error"
    if "connection" in lowered or "refused" in lowered:
        return "connection_error"
    if "parse" in lowered:
        return "parse_error"
    if "db" in lowered or "database" in lowered or "sql" in lowered:
        return "db_error"
    if "llm" in lowered or "model" in lowered:
        return "llm_error"
    if "missing key" in lowered or "api key" in lowered:
        return "missing_key"
    if "breaker" in lowered:
        return "source_breaker_open"
    if "stale_run_timeout" in lowered:
        return "stale_run_timeout"
    return "unknown"


def action_for_failure(failure_type: str) -> str:
    normalized = failure_type.strip().lower()
    if normalized not in FAILURE_TYPES:
        normalized = "unknown"
    return SAFE_ACTION_BY_FAILURE[normalized]


async def record_healing_incident(
    session: AsyncSession,
    *,
    component: str,
    failure_type: str,
    action: str | None = None,
    result: str = "applied",
    duration_ms: int = 0,
    auto_applied: bool = True,
    escalated: bool = False,
    details: dict | None = None,
    error_message: str | None = None,
) -> HealingIncident:
    normalized_failure = failure_type if failure_type in FAILURE_TYPES else "unknown"
    row = HealingIncident(
        component=component,
        failure_type=normalized_failure,
        action=action or action_for_failure(normalized_failure),
        result=result,
        duration_ms=max(0, int(duration_ms)),
        auto_applied=bool(auto_applied),
        escalated=bool(escalated),
        details=details or {},
        error_message=error_message,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def serialize_incident(row: HealingIncident) -> dict:
    return {
        "incident_id": str(row.incident_id),
        "component": row.component,
        "failure_type": row.failure_type,
        "action": row.action,
        "result": row.result,
        "duration_ms": int(row.duration_ms or 0),
        "auto_applied": bool(row.auto_applied),
        "escalated": bool(row.escalated),
        "details": row.details or {},
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_incidents(session: AsyncSession, *, limit: int = 50) -> list[dict]:
    safe_limit = max(1, min(int(limit), 200))
    rows = (
        await session.execute(
            select(HealingIncident).order_by(desc(HealingIncident.created_at)).limit(safe_limit)
        )
    ).scalars().all()
    return [serialize_incident(row) for row in rows]
