from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, cast, func, or_, select

from apps.agents.announcements.insight import (
    get_or_build_announcement_insight,
    refresh_announcement_context,
)
from apps.agents.announcements.severity import derive_severity
from apps.agents.announcements.registry import get_all_source_configs
from apps.agents.announcements.registry import get_source_configs
from apps.api.routers.auth import require_api_key
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.models import Announcement, SourceHealth

router = APIRouter(tags=["announcements"], dependencies=[Depends(require_api_key)])
settings = get_settings()


def _scope_label(scope: str | None) -> str:
    normalized = (scope or "kenya_core").strip().lower()
    if normalized == "global_outside":
        return "GLOBAL OUTSIDE"
    if normalized == "kenya_extended":
        return "KENYA EXTENDED"
    return "KENYA CORE"


def _build_stats_human_summary(
    *,
    total: int,
    alerted: int,
    unalerted: int,
    by_type: dict[str, int],
    by_source: dict[str, int],
) -> dict:
    if total <= 0:
        return {
            "headline": "No announcement records are currently stored.",
            "plain_summary": "The monitor has not persisted any disclosures yet.",
            "bullets": ["Run Agent B to ingest and classify disclosures."],
            "top_types": [],
            "top_sources": [],
        }

    top_types = sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:3]
    top_sources = sorted(by_source.items(), key=lambda x: x[1], reverse=True)[:3]
    severity_rollup = {"high": 0, "medium": 0, "low": 0}
    for ann_type, count in by_type.items():
        severity, _score = derive_severity(ann_type, 0.75)
        severity_rollup[severity] = int(severity_rollup.get(severity, 0)) + int(count)

    headline = (
        f"{total} disclosure records tracked: {severity_rollup['high']} high-severity, "
        f"{severity_rollup['medium']} medium, {severity_rollup['low']} low."
    )
    plain_summary = (
        f"Alert workflow: {alerted} alerted and {unalerted} pending/no-alert rows."
    )
    bullets = [
        "Top disclosure types: "
        + (", ".join(f"{k} ({v})" for k, v in top_types) if top_types else "none."),
        "Top source contribution: "
        + (", ".join(f"{k} ({v})" for k, v in top_sources) if top_sources else "none."),
    ]
    return {
        "headline": headline,
        "plain_summary": plain_summary,
        "bullets": bullets,
        "top_types": [{"type": k, "count": int(v)} for k, v in top_types],
        "top_sources": [{"source_id": k, "count": int(v)} for k, v in top_sources],
        "severity_rollup": severity_rollup,
    }


def _build_stats_human_summary_v2(human_summary: dict) -> dict:
    top_types = human_summary.get("top_types") if isinstance(human_summary.get("top_types"), list) else []
    top_sources = human_summary.get("top_sources") if isinstance(human_summary.get("top_sources"), list) else []
    return {
        "headline": human_summary.get("headline") or "Announcement monitor summary",
        "plain_summary": human_summary.get("plain_summary") or "No narrative available.",
        "key_drivers": list(human_summary.get("bullets") or []),
        "risks": [],
        "sector_highlights": [
            f"type:{row.get('type')} count:{int(row.get('count') or 0)}"
            for row in top_types[:3]
            if isinstance(row, dict)
        ],
        "ticker_insights": [],
        "quality": {
            "coverage_pct": 100.0,
            "freshness_score": 100.0,
            "confidence_score": 90.0,
            "degradation_flags": [],
        },
        "evidence_refs": [
            {
                "type": "source_rollup",
                "source_id": str(row.get("source_id") or "unknown"),
                "timestamp": None,
                "url_or_id": f"source:{row.get('source_id')}",
                "confidence": None,
            }
            for row in top_sources[:5]
            if isinstance(row, dict)
        ],
        "next_watch": [],
    }


@router.get("/announcements")
async def list_announcements(
    ticker: str | None = None,
    type: str | None = None,  # noqa: A002
    source_id: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    alerted: bool | None = None,
    dedupe: bool = True,
    scope: str | None = None,
    theme: str | None = None,
    kenya_impact_min: int | None = None,
    global_only: bool = False,
    limit: int = 50,
    offset: int = 0,
):
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    async with get_session() as session:
        stmt = select(Announcement)
        scope_expr = func.coalesce(Announcement.raw_payload["scope"].astext, "kenya_core")
        theme_expr = Announcement.raw_payload["theme"].astext
        impact_expr = cast(func.coalesce(Announcement.raw_payload["kenya_impact_score"].astext, "100"), Float)

        if ticker:
            stmt = stmt.where(Announcement.ticker == ticker.upper())
        if type:
            stmt = stmt.where(Announcement.announcement_type == type)
        if source_id:
            stmt = stmt.where(Announcement.source_id == source_id)
        if from_:
            stmt = stmt.where(Announcement.announcement_date >= from_)
        if to:
            stmt = stmt.where(Announcement.announcement_date <= to)
        if alerted is not None:
            stmt = stmt.where(Announcement.alerted.is_(alerted))
        if scope and scope != "all":
            stmt = stmt.where(scope_expr == scope)
        if theme:
            stmt = stmt.where(theme_expr == theme)
        if kenya_impact_min is not None:
            stmt = stmt.where(impact_expr >= max(0, min(int(kenya_impact_min), 100)))
        if global_only:
            stmt = stmt.where(scope_expr == "global_outside")
        elif scope is None:
            threshold = max(0, min(int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD), 100))
            stmt = stmt.where(
                or_(
                    scope_expr != "global_outside",
                    impact_expr >= threshold,
                )
            )

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(total_stmt)).scalar_one()

        stmt = (
            stmt.order_by(Announcement.announcement_date.desc().nullslast(), Announcement.first_seen_at.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        )

        rows = (await session.execute(stmt)).scalars().all()

    stop_words = {"a", "an", "the", "and", "or", "for", "in", "on", "to", "of", "by", "with", "at", "from"}
    seen_canonical: set[str] = set()
    seen_headline: set[str] = set()
    items = []
    for row in rows:
        raw_payload = getattr(row, "raw_payload", None) or {}
        item_scope = str(raw_payload.get("scope") or "kenya_core")
        item_theme = raw_payload.get("theme")
        item_impact = raw_payload.get("kenya_impact_score")
        try:
            item_impact_num = int(item_impact) if item_impact is not None else (100 if item_scope != "global_outside" else 0)
        except Exception:
            item_impact_num = 100 if item_scope != "global_outside" else 0
        severity, severity_score = derive_severity(row.announcement_type, float(row.type_confidence))
        ticker_key = str(row.ticker or "unmapped").upper()
        type_key = str(row.announcement_type or "other").lower()
        canonical = str(row.canonical_url or row.url or "").strip().lower()
        normalized_headline = re.sub(r"[^a-z0-9\s]", " ", str(row.headline or "").lower())
        normalized_headline = " ".join(
            token for token in normalized_headline.split() if token and token not in stop_words
        )[:180]
        headline_key = f"{ticker_key}|{type_key}|headline:{normalized_headline}"
        canonical_key = f"{ticker_key}|{type_key}|url:{canonical}" if canonical else None
        if dedupe and (
            (canonical_key is not None and canonical_key in seen_canonical)
            or headline_key in seen_headline
        ):
            continue
        if dedupe:
            if canonical_key is not None:
                seen_canonical.add(canonical_key)
            seen_headline.add(headline_key)
        items.append(
            {
            "announcement_id": row.announcement_id,
            "source_id": row.source_id,
            "ticker": row.ticker,
            "company": row.company_name,
            "headline": row.headline,
            "url": row.url,
            "canonical_url": row.canonical_url,
            "announcement_date": row.announcement_date.isoformat() if row.announcement_date else None,
            "announcement_type": row.announcement_type,
            "type_confidence": float(row.type_confidence),
            "details": row.details,
            "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "alerted": row.alerted,
            "alerted_at": row.alerted_at.isoformat() if row.alerted_at else None,
            "severity": raw_payload.get("severity") or severity,
            "severity_score": raw_payload.get("severity_score") if raw_payload.get("severity_score") is not None else severity_score,
            "scope": item_scope,
            "source_scope_label": _scope_label(item_scope),
            "theme": item_theme,
            "signal_class": raw_payload.get("signal_class"),
            "market_region": raw_payload.get("market_region"),
            "kenya_impact_score": item_impact_num,
            "affected_sectors": raw_payload.get("affected_sectors") or [],
            "transmission_channels": raw_payload.get("transmission_channels") or [],
            "promoted_to_core_feed": bool(raw_payload.get("promoted_to_core_feed", item_scope != "global_outside")),
            "alpha_context": raw_payload.get("alpha_context"),
        }
        )

    return {"items": items, "total": int(total), "limit": safe_limit, "offset": safe_offset}


@router.get("/announcements/stats")
async def announcements_stats():
    async with get_session() as session:
        theme_expr = func.coalesce(Announcement.raw_payload["theme"].astext, "unclassified")
        scope_expr = func.coalesce(Announcement.raw_payload["scope"].astext, "kenya_core")
        impact_expr = cast(func.coalesce(Announcement.raw_payload["kenya_impact_score"].astext, "0"), Float)
        high_impact_threshold = float(max(0, min(int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD), 100)))

        total = (await session.execute(select(func.count()).select_from(Announcement))).scalar_one()
        alerted = (
            await session.execute(
                select(func.count()).select_from(Announcement).where(Announcement.alerted.is_(True))
            )
        ).scalar_one()
        unalerted = (
            await session.execute(
                select(func.count()).select_from(Announcement).where(Announcement.alerted.is_(False))
            )
        ).scalar_one()

        by_type_rows = (
            await session.execute(
                select(Announcement.announcement_type, func.count())
                .group_by(Announcement.announcement_type)
                .order_by(func.count().desc())
            )
        ).all()

        by_source_rows = (
            await session.execute(
                select(Announcement.source_id, func.count())
                .group_by(Announcement.source_id)
                .order_by(func.count().desc())
            )
        ).all()
        theme_rows = (
            await session.execute(
                select(
                    theme_expr,
                    func.count(),
                )
                .group_by(theme_expr)
                .order_by(func.count().desc())
            )
        ).all()
        high_impact_theme_rows = (
            await session.execute(
                select(
                    theme_expr,
                    func.count(),
                )
                .where(scope_expr == "global_outside")
                .where(impact_expr >= high_impact_threshold)
                .group_by(theme_expr)
                .order_by(func.count().desc())
            )
        ).all()
        high_impact_global_total = (
            await session.execute(
                select(func.count())
                .select_from(Announcement)
                .where(scope_expr == "global_outside")
                .where(impact_expr >= high_impact_threshold)
            )
        ).scalar_one()

    by_type = {row[0]: int(row[1]) for row in by_type_rows}
    by_source = {row[0]: int(row[1]) for row in by_source_rows}
    by_theme = {str(row[0]): int(row[1]) for row in theme_rows}
    high_impact_global_by_theme = {str(row[0]): int(row[1]) for row in high_impact_theme_rows}
    source_scope_map = {src.source_id: src.scope for src in get_all_source_configs()}
    kenya_core_total = 0
    kenya_extended_total = 0
    global_outside_total = 0
    for source_id, count in by_source.items():
        scope = source_scope_map.get(source_id, "kenya_core")
        if scope == "global_outside":
            global_outside_total += int(count)
        elif scope == "kenya_extended":
            kenya_extended_total += int(count)
        else:
            kenya_core_total += int(count)

    human_summary = _build_stats_human_summary(
        total=int(total),
        alerted=int(alerted),
        unalerted=int(unalerted),
        by_type=by_type,
        by_source=by_source,
    )

    return {
        "total": int(total),
        "alerted": int(alerted),
        "unalerted": int(unalerted),
        "by_type": by_type,
        "by_source": by_source,
        "kenya_core_total": int(kenya_core_total),
        "kenya_extended_total": int(kenya_extended_total),
        "global_outside_total": int(global_outside_total),
        "high_impact_global_total": int(high_impact_global_total),
        "by_theme": by_theme,
        "high_impact_global_by_theme": high_impact_global_by_theme,
        "global_impact_threshold": int(max(0, min(int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD), 100))),
        "human_summary": human_summary,
        "human_summary_v2": _build_stats_human_summary_v2(human_summary),
    }


@router.get("/announcements/{announcement_id}")
async def get_announcement(announcement_id: str):
    async with get_session() as session:
        row = (
            await session.execute(
                select(Announcement).where(Announcement.announcement_id == announcement_id)
            )
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found")

    raw_payload = getattr(row, "raw_payload", None) or {}
    severity, severity_score = derive_severity(row.announcement_type, float(row.type_confidence))
    return {
        "announcement_id": row.announcement_id,
        "source_id": row.source_id,
        "ticker": row.ticker,
        "company": row.company_name,
        "headline": row.headline,
        "url": row.url,
        "canonical_url": row.canonical_url,
        "announcement_date": row.announcement_date.isoformat() if row.announcement_date else None,
        "announcement_type": row.announcement_type,
        "type_confidence": float(row.type_confidence),
        "details": row.details,
        "content_hash": row.content_hash,
        "raw_payload": raw_payload,
        "alpha_context": raw_payload.get("alpha_context"),
        "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "alerted": row.alerted,
        "alerted_at": row.alerted_at.isoformat() if row.alerted_at else None,
        "classifier_version": row.classifier_version,
        "normalizer_version": row.normalizer_version,
        "severity": raw_payload.get("severity") or severity,
        "severity_score": raw_payload.get("severity_score") if raw_payload.get("severity_score") is not None else severity_score,
        "scope": raw_payload.get("scope") or "kenya_core",
        "source_scope_label": _scope_label(raw_payload.get("scope") or "kenya_core"),
        "theme": raw_payload.get("theme"),
        "signal_class": raw_payload.get("signal_class"),
        "market_region": raw_payload.get("market_region"),
        "kenya_impact_score": raw_payload.get("kenya_impact_score"),
        "affected_sectors": raw_payload.get("affected_sectors") or [],
        "transmission_channels": raw_payload.get("transmission_channels") or [],
    }


@router.get("/announcements/{announcement_id}/insight")
async def get_announcement_insight(
    announcement_id: str,
    refresh_context_if_needed: bool = True,
    force_regenerate: bool = False,
):
    now_utc = datetime.now(timezone.utc)
    async with get_session() as session:
        row = (
            await session.execute(
                select(Announcement).where(Announcement.announcement_id == announcement_id)
            )
        ).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail="Announcement not found")

        insight_payload, meta = await get_or_build_announcement_insight(
            row,
            refresh_context_if_needed=refresh_context_if_needed,
            force_regenerate=force_regenerate,
            now_utc=now_utc,
        )
        await session.commit()

    return {
        "announcement_id": announcement_id,
        "item": insight_payload,
        "meta": meta,
    }


@router.post("/announcements/{announcement_id}/context/refresh")
async def refresh_announcement_insight_context(announcement_id: str):
    now_utc = datetime.now(timezone.utc)
    async with get_session() as session:
        row = (
            await session.execute(
                select(Announcement).where(Announcement.announcement_id == announcement_id)
            )
        ).scalar_one_or_none()

        if row is None:
            raise HTTPException(status_code=404, detail="Announcement not found")

        result = await refresh_announcement_context(row, now_utc=now_utc)
        await session.commit()
        details_length = len((row.details or "").strip())
        last_seen_at = row.last_seen_at.isoformat() if row.last_seen_at else None
        url = row.url
        canonical_url = row.canonical_url

    return {
        "announcement_id": announcement_id,
        "refresh": result,
        "details_length": details_length,
        "last_seen_at": last_seen_at,
        "url": url,
        "canonical_url": canonical_url,
    }


@router.get("/sources/health")
async def source_health():
    configured = {cfg.source_id: cfg for cfg in get_all_source_configs()}
    enabled_now = {cfg.source_id for cfg in get_source_configs()}
    now_utc = datetime.now(timezone.utc)
    threshold_24h = now_utc - timedelta(hours=24)
    async with get_session() as session:
        rows = (
            await session.execute(select(SourceHealth).order_by(SourceHealth.source_id.asc()))
        ).scalars().all()

    by_source = {row.source_id: row for row in rows}
    all_ids = sorted(set(configured.keys()) | set(by_source.keys()))

    items = []
    for source_id in all_ids:
        row = by_source.get(source_id)
        cfg = configured.get(source_id)
        last_metrics = row.last_metrics if row else {}
        last_error_type = (last_metrics or {}).get("last_error_type") or (last_metrics or {}).get("error_type")
        success_count = int((last_metrics or {}).get("success_count_24h") or 0)
        failure_count = int((last_metrics or {}).get("failure_count_24h") or 0)
        blocked_count_24h = int((last_metrics or {}).get("blocked_count_24h") or 0)
        denom = success_count + failure_count
        success_rate_24h: float | None = round(success_count / denom, 4) if denom > 0 else None

        if success_rate_24h is None:
            # Backward-compatible fallback for rows created before 24h counters existed.
            if row and row.last_success_at and row.last_success_at >= threshold_24h:
                success_rate_24h = 1.0
            if row and row.last_failure_at and row.last_failure_at >= threshold_24h and success_rate_24h is None:
                success_rate_24h = 0.0

        items.append(
            {
                "source_id": source_id,
                "enabled": source_id in enabled_now,
                "tier": cfg.tier if cfg else "secondary",
                "required_for_success": bool(cfg.required_for_success) if cfg else False,
                "scope": cfg.scope if cfg else "kenya_core",
                "theme": cfg.theme if cfg else None,
                "signal_class": cfg.signal_class if cfg else None,
                "disabled_reason": cfg.disabled_reason if cfg else None,
                "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
                "last_failure_at": row.last_failure_at.isoformat() if row and row.last_failure_at else None,
                "consecutive_failures": row.consecutive_failures if row else 0,
                "breaker_state": row.breaker_state if row else "closed",
                "cooldown_until": row.cooldown_until.isoformat() if row and row.cooldown_until else None,
                "last_error_type": last_error_type,
                "success_rate_24h": success_rate_24h,
                "blocked_count_24h": blocked_count_24h,
                "last_metrics": last_metrics,
            }
        )

    return {
        "items": items
    }
