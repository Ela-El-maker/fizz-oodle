from __future__ import annotations

from datetime import date
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select

from apps.agents.briefing.registry import get_briefing_source_configs
from apps.api.routers.auth import require_api_key
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.global_source_packs import source_allowed_by_pack
from apps.core.models import DailyBriefing, SourceHealth

router = APIRouter(tags=["briefings"], dependencies=[Depends(require_api_key)])
settings = get_settings()


@router.get("/briefings/latest")
async def briefing_latest():
    async with get_session() as session:
        row = (await session.execute(select(DailyBriefing).order_by(desc(DailyBriefing.briefing_date)).limit(1))).scalars().first()

    if row is None:
        return {"item": None}

    return {
        "item": {
            "briefing_date": str(row.briefing_date),
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "status": row.status,
            "subject": row.subject,
            "html_content": row.html_content,
            "metrics": row.metrics,
            "human_summary": (row.metrics or {}).get("human_summary") if isinstance(row.metrics, dict) else None,
            "human_summary_v2": (row.metrics or {}).get("human_summary_v2") if isinstance(row.metrics, dict) else None,
            "email_sent_at": row.email_sent_at.isoformat() if row.email_sent_at else None,
            "email_error": row.email_error,
            "payload_hash": row.payload_hash,
        }
    }


@router.get("/briefing/sources/health")
async def briefing_sources_health():
    configured = get_briefing_source_configs()
    now_utc = datetime.now(timezone.utc)
    threshold_24h = now_utc - timedelta(hours=24)
    async with get_session() as session:
        rows = (
            await session.execute(
                select(SourceHealth).where(SourceHealth.source_id.in_(tuple(configured.keys())))
            )
        ).scalars().all()

    by_source = {row.source_id: row for row in rows}
    items = []
    for source_id, cfg in sorted(configured.items()):
        enabled = bool(cfg.enabled_by_default)
        if cfg.type == "sitemap" and not settings.ENABLE_SITEMAP_SOURCES:
            enabled = False
        if cfg.scope == "global_outside" and not settings.ENABLE_GLOBAL_OUTSIDE_SOURCES:
            enabled = False
        if not source_allowed_by_pack(
            source_id=cfg.source_id,
            enable_theme_pack=bool(settings.ENABLE_GLOBAL_MARKETS_THEME_PACK),
            enable_extras_pack=bool(settings.ENABLE_GLOBAL_EXTRAS_PACK),
        ):
            enabled = False
        if cfg.premium and not settings.ENABLE_PREMIUM_GLOBAL_SOURCES:
            enabled = False
        row = by_source.get(source_id)
        last_metrics = row.last_metrics if row else {}
        success_count = int((last_metrics or {}).get("success_count_24h") or 0)
        failure_count = int((last_metrics or {}).get("failure_count_24h") or 0)
        blocked_count_24h = int((last_metrics or {}).get("blocked_count_24h") or 0)
        denom = success_count + failure_count
        success_rate_24h: float | None = round(success_count / denom, 4) if denom > 0 else None
        if success_rate_24h is None:
            if row and row.last_success_at and row.last_success_at >= threshold_24h:
                success_rate_24h = 1.0
            if row and row.last_failure_at and row.last_failure_at >= threshold_24h and success_rate_24h is None:
                success_rate_24h = 0.0

        items.append(
            {
                "source_id": source_id,
                "channel": cfg.channel,
                "tier": cfg.tier,
                "required_for_success": bool(cfg.required_for_success),
                "enabled": enabled,
                "scope": cfg.scope,
                "theme": cfg.theme,
                "signal_class": cfg.signal_class,
                "disabled_reason": cfg.disabled_reason,
                "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
                "last_failure_at": row.last_failure_at.isoformat() if row and row.last_failure_at else None,
                "consecutive_failures": int(row.consecutive_failures) if row else 0,
                "breaker_state": row.breaker_state if row else "closed",
                "cooldown_until": row.cooldown_until.isoformat() if row and row.cooldown_until else None,
                "last_error_type": (last_metrics or {}).get("last_error_type"),
                "success_rate_24h": success_rate_24h,
                "blocked_count_24h": blocked_count_24h,
                "last_metrics": last_metrics,
            }
        )
    return {"items": items}


@router.get("/briefings/daily")
async def briefing_daily(date: date):
    async with get_session() as session:
        row = (
            await session.execute(
                select(DailyBriefing).where(DailyBriefing.briefing_date == date).limit(1)
            )
        ).scalars().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Briefing not found")

    return {
        "item": {
            "briefing_date": str(row.briefing_date),
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "status": row.status,
            "subject": row.subject,
            "html_content": row.html_content,
            "metrics": row.metrics,
            "human_summary": (row.metrics or {}).get("human_summary") if isinstance(row.metrics, dict) else None,
            "human_summary_v2": (row.metrics or {}).get("human_summary_v2") if isinstance(row.metrics, dict) else None,
            "email_sent_at": row.email_sent_at.isoformat() if row.email_sent_at else None,
            "email_error": row.email_error,
            "payload_hash": row.payload_hash,
        }
    }


@router.get("/internal/email/executive/latest")
async def executive_email_latest():
    async with get_session() as session:
        row = (
            await session.execute(select(DailyBriefing).order_by(desc(DailyBriefing.briefing_date)).limit(1))
        ).scalars().first()

    if row is None:
        return {"item": None}

    metrics = row.metrics if isinstance(row.metrics, dict) else {}
    return {
        "item": {
            "briefing_date": str(row.briefing_date),
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "subject": metrics.get("executive_digest_subject") or row.subject,
            "html_content": row.html_content,
            "executive_digest_sent": bool(metrics.get("executive_digest_sent")),
            "executive_digest_sent_at": metrics.get("executive_digest_sent_at"),
            "executive_digest_error": metrics.get("executive_digest_error"),
            "executive_digest_story_count": int(metrics.get("executive_digest_story_count") or 0),
            "executive_digest_sections": metrics.get("executive_digest_sections") or [],
        }
    }
