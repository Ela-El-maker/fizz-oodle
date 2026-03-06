from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.autonomy_policy import get_latest_autonomy_state
from apps.core.config import get_settings
from apps.core.healing_engine import list_incidents
from apps.core.learning_engine import get_latest_learning_summary
from apps.core.models import SelfModificationAction, SelfModificationProposal
from apps.core.runtime_overrides import load_runtime_overrides, store_runtime_overrides

settings = get_settings()

SECONDARY_SOURCE_IDS_BY_AGENT: dict[str, list[str]] = {
    "briefing": [
        "standard_rss",
        "google_news_ke",
        "bbc_business_rss",
        "business_daily_html",
        "the_star_html",
        "standard_business_html",
        "mystocks_news",
    ],
    "announcements": [
        "standard_business",
        "business_daily_markets",
        "the_star_business",
        "reuters_africa",
        "bloomberg_africa",
        "cma_notices",
        "cma_market_announcements",
    ],
    "sentiment": [
        "reddit_rss",
        "business_daily_rss",
        "the_star_business_rss",
        "x_search_api",
        "youtube_api",
        "mystocks_forum",
        "stockswatch_forum",
        "business_daily_comments",
        "standardmedia_comments",
    ],
}

AGENT_BY_SOURCE_ID = {
    source_id: agent for agent, source_ids in SECONDARY_SOURCE_IDS_BY_AGENT.items() for source_id in source_ids
}


def _fingerprint_for(*, agent_name: str | None, proposal_type: str, changes: dict[str, Any]) -> str:
    payload = {"agent_name": agent_name, "proposal_type": proposal_type, "changes": changes}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _serialize_proposal(row: SelfModificationProposal) -> dict[str, Any]:
    return {
        "proposal_id": str(row.proposal_id),
        "scope": row.scope,
        "agent_name": row.agent_name,
        "proposal_type": row.proposal_type,
        "risk_level": row.risk_level,
        "status": row.status,
        "reason": row.reason,
        "evidence": row.evidence_json or {},
        "changes": row.changes_json or {},
        "fingerprint": row.fingerprint,
        "auto_eligible": bool(row.auto_eligible),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "applied_at": row.applied_at.isoformat() if row.applied_at else None,
    }


def _serialize_action(row: SelfModificationAction) -> dict[str, Any]:
    return {
        "action_id": str(row.action_id),
        "proposal_id": str(row.proposal_id) if row.proposal_id else None,
        "action_type": row.action_type,
        "target": row.target,
        "payload": row.payload_json or {},
        "result": row.result,
        "error_message": row.error_message,
        "auto_applied": bool(row.auto_applied),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _proposal(
    *,
    scope: str,
    agent_name: str | None,
    proposal_type: str,
    reason: str,
    changes: dict[str, Any],
    evidence: dict[str, Any],
    risk_level: str = "low",
    auto_eligible: bool = True,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "agent_name": agent_name,
        "proposal_type": proposal_type,
        "risk_level": risk_level,
        "reason": reason,
        "changes": changes,
        "evidence": evidence,
        "auto_eligible": auto_eligible,
        "fingerprint": _fingerprint_for(agent_name=agent_name, proposal_type=proposal_type, changes=changes),
    }


def build_self_mod_proposals(
    *,
    autonomy_state: dict[str, Any],
    learning_summary: dict[str, Any],
    healing_incidents: list[dict[str, Any]],
    runtime_overrides: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    safe_mode = bool(autonomy_state.get("safe_mode"))
    recommendations = (
        learning_summary.get("source_adaptation_recommendations", [])
        if isinstance(learning_summary, dict)
        else []
    )

    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        agent_name = str(rec.get("agent_name") or "").strip().lower()
        if not agent_name:
            continue
        action = str(rec.get("action") or "").strip().lower()
        reason = str(rec.get("reason") or "adaptive_policy")
        source_ids = SECONDARY_SOURCE_IDS_BY_AGENT.get(agent_name, [])
        if not source_ids:
            continue

        if action == "throttle_secondary_sources":
            changes = {
                "sources": {
                    source_id: {"rate_limit_multiplier": 0.7, "max_items_per_run": 200} for source_id in source_ids
                }
            }
            out.append(
                _proposal(
                    scope="scraper",
                    agent_name=agent_name,
                    proposal_type="throttle_secondary_sources",
                    reason=reason,
                    changes=changes,
                    evidence={"recommendation": rec},
                )
            )
        elif action == "increase_fallback_priority" and agent_name == "briefing":
            out.append(
                _proposal(
                    scope="scraper",
                    agent_name=agent_name,
                    proposal_type="prefer_stable_news_order",
                    reason=reason,
                    changes={
                        "channel_order": {
                            "news": [
                                "standard_rss",
                                "google_news_ke",
                                "bbc_business_rss",
                                "mystocks_news",
                                "business_daily_html",
                                "the_star_html",
                                "standard_business_html",
                            ]
                        }
                    },
                    evidence={"recommendation": rec},
                )
            )

    if safe_mode:
        out.append(
            _proposal(
                scope="scraper",
                agent_name="sentiment",
                proposal_type="safe_mode_disable_noisy_sources",
                reason="safe_mode_active",
                changes={
                    "sources": {
                        "reddit_rss": {"enabled": False},
                        "x_search_api": {"enabled": False},
                    }
                },
                evidence={"safe_mode": True},
            )
        )

    for incident in healing_incidents:
        if not isinstance(incident, dict):
            continue
        failure_type = str(incident.get("failure_type") or "")
        component = str(incident.get("component") or "")
        if failure_type not in {"blocked", "rate_limited"}:
            continue
        if not component.startswith("source:"):
            continue
        source_id = component.split(":", 1)[1].strip()
        agent_name = AGENT_BY_SOURCE_ID.get(source_id)
        if not agent_name:
            continue
        out.append(
            _proposal(
                scope="scraper",
                agent_name=agent_name,
                proposal_type="cooldown_unstable_source",
                reason=f"{failure_type}_detected",
                changes={"sources": {source_id: {"enabled": False, "cooldown_minutes": 120}}},
                evidence={"incident": incident},
            )
        )

    # ── Cooldown recovery: re-enable disabled sources when safe_mode is off
    # and no recent blocking/rate-limiting incidents exist for that source ──
    if not safe_mode:
        incident_source_ids: set[str] = set()
        for incident in healing_incidents:
            if not isinstance(incident, dict):
                continue
            comp = str(incident.get("component") or "")
            if comp.startswith("source:"):
                incident_source_ids.add(comp.split(":", 1)[1].strip())

        current_overrides = runtime_overrides or {}
        agents_cfg = current_overrides.get("agents") or {}
        for agent_name, agent_cfg in agents_cfg.items():
            if not isinstance(agent_cfg, dict):
                continue
            sources_cfg = agent_cfg.get("sources") or {}
            if not isinstance(sources_cfg, dict):
                continue
            for source_id, source_cfg in sources_cfg.items():
                if not isinstance(source_cfg, dict):
                    continue
                if source_cfg.get("enabled") is False and source_id not in incident_source_ids:
                    out.append(
                        _proposal(
                            scope="scraper",
                            agent_name=agent_name,
                            proposal_type="reenable_recovered_source",
                            reason="no_recent_incidents",
                            changes={"sources": {source_id: {"enabled": True, "cooldown_minutes": 0}}},
                            evidence={"source_id": source_id},
                        )
                    )

    deduped: dict[str, dict[str, Any]] = {}
    for row in out:
        deduped[row["fingerprint"]] = row
    return list(deduped.values())


async def list_self_mod_proposals(session: AsyncSession, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 200))
    stmt = select(SelfModificationProposal).order_by(desc(SelfModificationProposal.created_at)).limit(safe_limit)
    if status:
        stmt = stmt.where(SelfModificationProposal.status == status.strip().lower())
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize_proposal(row) for row in rows]


async def _merge_runtime_changes(*, overrides: dict[str, Any], agent_name: str, changes: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(overrides if isinstance(overrides, dict) else {})
    agents = merged.setdefault("agents", {})
    if not isinstance(agents, dict):
        agents = {}
        merged["agents"] = agents
    agent_payload = agents.setdefault(agent_name, {})
    if not isinstance(agent_payload, dict):
        agent_payload = {}
        agents[agent_name] = agent_payload

    source_changes = changes.get("sources")
    if isinstance(source_changes, dict):
        sources = agent_payload.setdefault("sources", {})
        if not isinstance(sources, dict):
            sources = {}
            agent_payload["sources"] = sources
        for source_id, patch in source_changes.items():
            if not isinstance(patch, dict):
                continue
            current = sources.get(source_id, {})
            if not isinstance(current, dict):
                current = {}
            current.update(patch)
            sources[source_id] = current

    channel_order = changes.get("channel_order")
    if isinstance(channel_order, dict):
        existing = agent_payload.setdefault("channel_order", {})
        if not isinstance(existing, dict):
            existing = {}
            agent_payload["channel_order"] = existing
        for channel, source_ids in channel_order.items():
            if isinstance(source_ids, list):
                existing[channel] = [str(item).strip().lower() for item in source_ids if str(item).strip()]

    return merged


async def apply_self_mod_proposal(
    session: AsyncSession,
    *,
    proposal_id: UUID,
    auto_applied: bool,
) -> dict[str, Any]:
    row = (
        await session.execute(select(SelfModificationProposal).where(SelfModificationProposal.proposal_id == proposal_id).limit(1))
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("proposal_not_found")
    if row.status == "applied":
        actions = (
            await session.execute(
                select(SelfModificationAction)
                .where(SelfModificationAction.proposal_id == row.proposal_id)
                .order_by(desc(SelfModificationAction.created_at))
                .limit(1)
            )
        ).scalars().first()
        return {"proposal": _serialize_proposal(row), "action": _serialize_action(actions) if actions else None}
    if auto_applied and not row.auto_eligible:
        raise ValueError("proposal_not_auto_eligible")

    now_utc = datetime.now(timezone.utc)
    result = "applied"
    error_message: str | None = None

    try:
        current = await load_runtime_overrides()
        agent_name = row.agent_name or "platform"
        merged = await _merge_runtime_changes(overrides=current, agent_name=agent_name, changes=row.changes_json or {})
        await store_runtime_overrides(merged)
        row.status = "applied"
        row.applied_at = now_utc
    except Exception as exc:  # noqa: PERF203
        result = "failed"
        error_message = str(exc)
        row.status = "failed"

    action = SelfModificationAction(
        proposal_id=row.proposal_id,
        action_type=row.proposal_type,
        target=row.agent_name or row.scope,
        payload_json=row.changes_json or {},
        result=result,
        error_message=error_message,
        auto_applied=bool(auto_applied),
        created_at=now_utc,
    )
    session.add(action)
    await session.commit()
    await session.refresh(row)
    await session.refresh(action)
    return {"proposal": _serialize_proposal(row), "action": _serialize_action(action)}


async def generate_self_mod_proposals(
    session: AsyncSession,
    *,
    refresh: bool = True,
    auto_apply: bool | None = None,
) -> dict[str, Any]:
    do_auto_apply = bool(settings.SELF_MOD_AUTO_APPLY_ENABLED if auto_apply is None else auto_apply)
    learning = await get_latest_learning_summary(session, refresh=refresh)
    autonomy = await get_latest_autonomy_state(session, refresh=refresh)
    incidents = await list_incidents(session, limit=200)
    current_overrides = await load_runtime_overrides()
    candidates = build_self_mod_proposals(
        autonomy_state=autonomy,
        learning_summary=learning.get("summary") or {},
        healing_incidents=incidents,
        runtime_overrides=current_overrides,
    )
    if not candidates:
        return {"created": 0, "applied": 0, "items": [], "auto_apply": do_auto_apply}

    lookback = datetime.now(timezone.utc) - timedelta(hours=24)
    fingerprints = [str(item["fingerprint"]) for item in candidates]
    existing = (
        await session.execute(
            select(SelfModificationProposal)
            .where(SelfModificationProposal.fingerprint.in_(fingerprints))
            .where(SelfModificationProposal.created_at >= lookback)
            .where(SelfModificationProposal.status.in_(["pending", "applied"]))
        )
    ).scalars().all()
    existing_fingerprints = {row.fingerprint for row in existing}

    created_rows: list[SelfModificationProposal] = []
    for item in candidates:
        if item["fingerprint"] in existing_fingerprints:
            continue
        row = SelfModificationProposal(
            scope=item["scope"],
            agent_name=item["agent_name"],
            proposal_type=item["proposal_type"],
            risk_level=item["risk_level"],
            status="pending",
            reason=item["reason"],
            evidence_json=item["evidence"],
            changes_json=item["changes"],
            fingerprint=item["fingerprint"],
            auto_eligible=bool(item["auto_eligible"]),
            created_by="learning_engine",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        created_rows.append(row)

    await session.commit()
    for row in created_rows:
        await session.refresh(row)

    applied = 0
    materialized_items: list[dict[str, Any]] = []
    for row in created_rows:
        item = {"proposal": _serialize_proposal(row), "action": None}
        if do_auto_apply and row.auto_eligible and row.risk_level == "low":
            result = await apply_self_mod_proposal(session, proposal_id=row.proposal_id, auto_applied=True)
            item = result
            if result["proposal"]["status"] == "applied":
                applied += 1
        materialized_items.append(item)

    return {
        "created": len(created_rows),
        "applied": applied,
        "items": materialized_items,
        "auto_apply": do_auto_apply,
    }


async def get_self_mod_state(session: AsyncSession) -> dict[str, Any]:
    runtime = await load_runtime_overrides()
    pending_count = (
        await session.execute(select(SelfModificationProposal).where(SelfModificationProposal.status == "pending"))
    ).scalars().all()
    applied_last_24h_count = (
        await session.execute(
            select(SelfModificationProposal)
            .where(SelfModificationProposal.status == "applied")
            .where(SelfModificationProposal.applied_at >= datetime.now(timezone.utc) - timedelta(hours=24))
        )
    ).scalars().all()
    last_action = (
        await session.execute(select(SelfModificationAction).order_by(desc(SelfModificationAction.created_at)).limit(1))
    ).scalar_one_or_none()
    return {
        "pending_count": len(pending_count),
        "applied_last_24h_count": len(applied_last_24h_count),
        "last_action_at": last_action.created_at.isoformat() if last_action and last_action.created_at else None,
        "runtime_overrides": runtime,
    }

