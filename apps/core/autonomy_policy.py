from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.config import get_settings
from apps.core.models import AgentRun, AutonomyState

settings = get_settings()
TERMINAL_STATUSES = {"success", "partial", "fail"}


def compute_priority_score(
    *,
    staleness: float,
    impact: float,
    anomaly: float,
    dependency_readiness: float,
    cost_penalty: float,
) -> float:
    return round(
        (0.35 * staleness)
        + (0.30 * impact)
        + (0.20 * anomaly)
        + (0.15 * dependency_readiness)
        - cost_penalty,
        4,
    )


def _active_policies() -> dict:
    return {
        "stale_reconciler_enabled": bool(settings.STALE_RUN_RECONCILER_ENABLED),
        "conservative_automation": True,
        "db_first_api_fallback": True,
        "stale_ttl_minutes": {
            "briefing": int(settings.BRIEFING_STALE_RUN_TTL_MINUTES),
            "announcements": int(settings.ANNOUNCEMENTS_STALE_RUN_TTL_MINUTES),
            "sentiment": int(settings.SENTIMENT_STALE_RUN_TTL_MINUTES),
            "analyst": int(settings.ANALYST_STALE_RUN_TTL_MINUTES),
            "archivist": int(settings.ARCHIVIST_STALE_RUN_TTL_MINUTES),
        },
    }


def summarize_runs(rows: list[AgentRun]) -> dict:
    by_agent: dict[str, dict] = defaultdict(lambda: {"total": 0, "terminal": 0, "status_counts": defaultdict(int)})
    terminal_total = 0
    for row in rows:
        by_agent[row.agent_name]["total"] += 1
        by_agent[row.agent_name]["status_counts"][row.status] += 1
        if row.status in TERMINAL_STATUSES:
            by_agent[row.agent_name]["terminal"] += 1
            terminal_total += 1

    serialized = {}
    for agent_name, payload in by_agent.items():
        total = int(payload["total"])
        terminal = int(payload["terminal"])
        serialized[agent_name] = {
            "total": total,
            "terminal": terminal,
            "terminality_pct": round((terminal / total) * 100.0, 2) if total else 0.0,
            "status_counts": dict(payload["status_counts"]),
        }

    total = len(rows)
    return {
        "run_count_window": total,
        "terminal_runs_window": terminal_total,
        "terminality_pct": round((terminal_total / total) * 100.0, 2) if total else 0.0,
        "by_agent": serialized,
    }


async def recompute_autonomy_state(session: AsyncSession) -> dict:
    now_utc = datetime.now(timezone.utc)
    lookback_start = now_utc - timedelta(hours=72)

    recent_rows = (
        await session.execute(
            select(AgentRun).where(AgentRun.started_at >= lookback_start).order_by(AgentRun.started_at.desc()).limit(2000)
        )
    ).scalars().all()
    running_count = (
        await session.execute(
            select(AgentRun).where(AgentRun.status == "running")
        )
    ).scalars().all()

    run_summary = summarize_runs(recent_rows)
    queue_depth = len(running_count)
    terminality_pct = float(run_summary.get("terminality_pct") or 0.0)
    # safe_mode when queue is dangerously deep or too many runs stuck non-terminal
    safe_mode = queue_depth > 25 or terminality_pct < 90.0

    active_policies = _active_policies()
    summary = {
        "window_hours": 72,
        "queue_depth": queue_depth,
        "safe_mode": safe_mode,
        "runs": run_summary,
    }

    state = (
        await session.execute(
            select(AutonomyState).where(AutonomyState.state_key == "global").limit(1)
        )
    ).scalar_one_or_none()
    if state is None:
        state = AutonomyState(state_key="global")
        session.add(state)

    state.queue_depth = queue_depth
    state.safe_mode = safe_mode
    state.active_policies = active_policies
    state.summary = summary
    state.last_policy_recompute_at = now_utc
    state.updated_at = now_utc
    await session.commit()

    return {
        "state_key": state.state_key,
        "queue_depth": state.queue_depth,
        "safe_mode": state.safe_mode,
        "active_policies": state.active_policies,
        "summary": state.summary,
        "last_policy_recompute_at": state.last_policy_recompute_at.isoformat() if state.last_policy_recompute_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


async def get_latest_autonomy_state(session: AsyncSession, *, refresh: bool = False) -> dict:
    if refresh:
        return await recompute_autonomy_state(session)

    row = (
        await session.execute(
            select(AutonomyState).where(AutonomyState.state_key == "global").order_by(desc(AutonomyState.updated_at)).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return await recompute_autonomy_state(session)

    return {
        "state_key": row.state_key,
        "queue_depth": row.queue_depth,
        "safe_mode": row.safe_mode,
        "active_policies": row.active_policies or {},
        "summary": row.summary or {},
        "last_policy_recompute_at": row.last_policy_recompute_at.isoformat() if row.last_policy_recompute_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
