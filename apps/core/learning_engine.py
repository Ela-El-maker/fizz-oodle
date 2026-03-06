from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.models import AgentRun, LearningSummary


def _rate(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 2)


def _extract_feedback_applied(metrics: dict) -> bool:
    return bool((metrics or {}).get("feedback_applied"))


def summarize_learning_from_runs(rows: list[AgentRun]) -> dict:
    by_agent: dict[str, dict] = defaultdict(lambda: {"total": 0, "success": 0, "partial": 0, "fail": 0})
    analyst_feedback_total = 0
    analyst_feedback_applied = 0
    archivist_promotions = 0
    archivist_lifecycle_updates = 0

    for row in rows:
        payload = by_agent[row.agent_name]
        payload["total"] += 1
        payload[row.status] = payload.get(row.status, 0) + 1

        metrics = row.metrics or {}
        if row.agent_name == "analyst":
            analyst_feedback_total += 1
            if _extract_feedback_applied(metrics):
                analyst_feedback_applied += 1
        if row.agent_name == "archivist":
            archivist_promotions += int(metrics.get("patterns_upserted") or 0)
            archivist_lifecycle_updates += int(metrics.get("lifecycle_updates") or 0)

    agent_scores: dict[str, dict] = {}
    for agent_name, stats in by_agent.items():
        total = int(stats["total"])
        success = int(stats.get("success", 0))
        partial = int(stats.get("partial", 0))
        fail = int(stats.get("fail", 0))
        agent_scores[agent_name] = {
            "total_runs": total,
            "success_runs": success,
            "partial_runs": partial,
            "failed_runs": fail,
            "completion_pct": _rate(success + partial + fail, total),
            "success_pct": _rate(success, total),
            "degradation_pct": _rate(partial, total),
            "failure_pct": _rate(fail, total),
        }

    adaptation_recommendations: list[dict] = []
    for agent_name in ("briefing", "announcements", "sentiment", "analyst", "archivist", "narrator"):
        stats = agent_scores.get(agent_name) or {}
        failure_pct = float(stats.get("failure_pct") or 0.0)
        degradation_pct = float(stats.get("degradation_pct") or 0.0)
        if failure_pct >= 10.0:
            adaptation_recommendations.append(
                {
                    "agent_name": agent_name,
                    "action": "throttle_secondary_sources",
                    "reason": f"failure_pct={failure_pct:.2f}",
                }
            )
        elif degradation_pct >= 20.0:
            adaptation_recommendations.append(
                {
                    "agent_name": agent_name,
                    "action": "increase_fallback_priority",
                    "reason": f"degradation_pct={degradation_pct:.2f}",
                }
            )

    return {
        "window_days": 28,
        "agent_scores": agent_scores,
        "feedback_loop": {
            "analyst_runs": analyst_feedback_total,
            "feedback_applied_runs": analyst_feedback_applied,
            "feedback_applied_rate_pct": _rate(analyst_feedback_applied, analyst_feedback_total),
        },
        "pattern_lifecycle": {
            "promotions_estimate": archivist_promotions,
            "lifecycle_updates": archivist_lifecycle_updates,
        },
        "source_adaptation_recommendations": adaptation_recommendations,
    }


async def recompute_learning_summary(session: AsyncSession) -> dict:
    now_utc = datetime.now(timezone.utc)
    lookback = now_utc - timedelta(days=28)
    rows = (
        await session.execute(
            select(AgentRun).where(AgentRun.started_at >= lookback).order_by(AgentRun.started_at.desc()).limit(5000)
        )
    ).scalars().all()
    summary = summarize_learning_from_runs(rows)

    row = LearningSummary(
        scope="platform",
        summary_json=summary,
        created_at=now_utc,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    return {
        "summary_id": str(row.summary_id),
        "scope": row.scope,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "summary": row.summary_json or {},
    }


async def get_latest_learning_summary(session: AsyncSession, *, refresh: bool = False) -> dict:
    if refresh:
        return await recompute_learning_summary(session)

    row = (
        await session.execute(
            select(LearningSummary).where(LearningSummary.scope == "platform").order_by(desc(LearningSummary.created_at)).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return await recompute_learning_summary(session)
    return {
        "summary_id": str(row.summary_id),
        "scope": row.scope,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "summary": row.summary_json or {},
    }
