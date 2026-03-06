from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select

from apps.agents.sentiment.themes import build_theme_summary_for_week
from apps.agents.sentiment.registry import get_all_source_configs, get_source_configs
from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.models import (
    SentimentDigestReport,
    SentimentRawPost,
    SentimentTickerMention,
    SentimentWeekly,
    SourceHealth,
)

router = APIRouter(tags=["sentiment"], dependencies=[Depends(require_api_key)])


def _serialize_weekly(row: SentimentWeekly) -> dict:
    return {
        "week_start": str(row.week_start),
        "ticker": row.ticker,
        "company_name": row.company_name,
        "mentions_count": row.mentions_count,
        "bullish_count": row.bullish_count,
        "bearish_count": row.bearish_count,
        "neutral_count": row.neutral_count,
        "bullish_pct": float(row.bullish_pct),
        "bearish_pct": float(row.bearish_pct),
        "neutral_pct": float(row.neutral_pct),
        "weighted_score": float(row.weighted_score),
        "confidence": float(row.confidence),
        "top_sources": row.top_sources or {},
        "notable_quotes": row.notable_quotes or [],
        "wow_delta": float(row.wow_delta) if row.wow_delta is not None else None,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


def _serialize_digest(row: SentimentDigestReport) -> dict:
    metrics = row.metrics or {}
    human_summary = metrics.get("human_summary") if isinstance(metrics, dict) else None
    human_summary_v2 = metrics.get("human_summary_v2") if isinstance(metrics, dict) else None
    theme_summary = metrics.get("theme_summary") if isinstance(metrics, dict) else None
    return {
        "week_start": str(row.week_start),
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "status": row.status,
        "subject": row.subject,
        "html_content": row.html_content,
        "html_path": row.html_path,
        "metrics": metrics,
        "human_summary": human_summary if isinstance(human_summary, dict) else None,
        "human_summary_v2": human_summary_v2 if isinstance(human_summary_v2, dict) else None,
        "theme_summary": theme_summary if isinstance(theme_summary, dict) else {"items": []},
        "email_sent_at": row.email_sent_at.isoformat() if row.email_sent_at else None,
        "email_error": row.email_error,
        "payload_hash": row.payload_hash,
    }


@router.get("/sentiment/weekly")
async def sentiment_weekly(
    week_start: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    async with get_session() as session:
        target_week = week_start
        if target_week is None:
            target_week = (
                await session.execute(select(SentimentWeekly.week_start).order_by(desc(SentimentWeekly.week_start)).limit(1))
            ).scalar_one_or_none()
            if target_week is None:
                return {"week_start": None, "items": [], "total": 0, "limit": limit, "offset": offset}

        base = select(SentimentWeekly).where(SentimentWeekly.week_start == target_week)
        total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = (
            await session.execute(
                base.order_by(SentimentWeekly.ticker.asc()).limit(limit).offset(offset)
            )
        ).scalars().all()

    return {
        "week_start": str(target_week),
        "items": [_serialize_weekly(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/sentiment/weekly/{ticker}")
async def sentiment_weekly_for_ticker(
    ticker: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
):
    t = ticker.upper()
    async with get_session() as session:
        stmt = select(SentimentWeekly).where(SentimentWeekly.ticker == t).order_by(SentimentWeekly.week_start.desc())
        if from_date:
            stmt = stmt.where(SentimentWeekly.week_start >= from_date)
        if to_date:
            stmt = stmt.where(SentimentWeekly.week_start <= to_date)
        rows = (await session.execute(stmt)).scalars().all()

    return {"ticker": t, "items": [_serialize_weekly(row) for row in rows]}


@router.get("/sentiment/raw")
async def sentiment_raw(
    ticker: str | None = None,
    source_id: str | None = None,
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    async with get_session() as session:
        stmt = select(SentimentTickerMention, SentimentRawPost).join(
            SentimentRawPost, SentimentTickerMention.post_id == SentimentRawPost.post_id
        )
        if ticker:
            stmt = stmt.where(SentimentTickerMention.ticker == ticker.upper())
        if source_id:
            stmt = stmt.where(SentimentRawPost.source_id == source_id)
        if from_dt:
            stmt = stmt.where(
                and_(
                    SentimentRawPost.published_at.is_not(None),
                    SentimentRawPost.published_at >= from_dt,
                )
            )
        if to_dt:
            stmt = stmt.where(
                and_(
                    SentimentRawPost.published_at.is_not(None),
                    SentimentRawPost.published_at <= to_dt,
                )
            )

        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (
            await session.execute(
                stmt.order_by(SentimentTickerMention.scored_at.desc()).limit(limit).offset(offset)
            )
        ).all()

    return {
        "items": [
            {
                "post_id": mention.post_id,
                "ticker": mention.ticker,
                "company_name": mention.company_name,
                "sentiment_label": mention.sentiment_label,
                "sentiment_score": float(mention.sentiment_score),
                "confidence": float(mention.confidence),
                "source_weight": float(mention.source_weight),
                "reasons": mention.reasons or {},
                "model_version": mention.model_version,
                "llm_used": mention.llm_used,
                "scored_at": mention.scored_at.isoformat() if mention.scored_at else None,
                "source_id": raw.source_id,
                "url": raw.url,
                "canonical_url": raw.canonical_url,
                "title": raw.title,
                "content": raw.content,
                "published_at": raw.published_at.isoformat() if raw.published_at else None,
                "fetched_at": raw.fetched_at.isoformat() if raw.fetched_at else None,
            }
            for mention, raw in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/sentiment/sources/health")
async def sentiment_sources_health():
    enabled = {src.source_id for src in get_source_configs()}
    configured = {src.source_id: src for src in get_all_source_configs()}
    now_utc = datetime.now(timezone.utc)
    threshold_24h = now_utc - timedelta(hours=24)
    async with get_session() as session:
        rows = (
            await session.execute(
                select(SourceHealth).where(SourceHealth.source_id.in_(tuple(configured.keys())))
            )
        ).scalars().all()

    by_id = {row.source_id: row for row in rows}
    items = []
    for source_id, source in sorted(configured.items()):
        row = by_id.get(source_id)
        last_metrics = row.last_metrics if row else {}
        last_error_type = (last_metrics or {}).get("last_error_type") or (last_metrics or {}).get("error_type")
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
                "type": source.type,
                "enabled": source_id in enabled,
                "weight": source.weight,
                "tier": source.tier,
                "required_for_success": bool(source.required_for_success),
                "requires_auth": source.requires_auth,
                "scope": source.scope,
                "theme": source.theme,
                "signal_class": source.signal_class,
                "disabled_reason": source.disabled_reason,
                "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
                "last_failure_at": row.last_failure_at.isoformat() if row and row.last_failure_at else None,
                "consecutive_failures": int(row.consecutive_failures) if row else 0,
                "breaker_state": row.breaker_state if row else "closed",
                "cooldown_until": row.cooldown_until.isoformat() if row and row.cooldown_until else None,
                "last_error_type": last_error_type,
                "success_rate_24h": success_rate_24h,
                "blocked_count_24h": blocked_count_24h,
                "last_metrics": last_metrics,
            }
        )
    return {"items": items}


@router.get("/sentiment/digest/latest")
async def sentiment_digest_latest():
    async with get_session() as session:
        row = (
            await session.execute(select(SentimentDigestReport).order_by(desc(SentimentDigestReport.week_start)).limit(1))
        ).scalars().first()

    if row is None:
        return {"item": None}
    return {"item": _serialize_digest(row)}


@router.get("/sentiment/digest")
async def sentiment_digest(week_start: date):
    async with get_session() as session:
        row = (
            await session.execute(select(SentimentDigestReport).where(SentimentDigestReport.week_start == week_start).limit(1))
        ).scalars().first()

    if row is None:
        raise HTTPException(status_code=404, detail="Sentiment digest not found")
    return {"item": _serialize_digest(row)}


@router.get("/sentiment/themes/weekly")
async def sentiment_themes_weekly(
    week_start: date | None = None,
):
    target_week = week_start
    async with get_session() as session:
        if target_week is None:
            target_week = (
                await session.execute(
                    select(SentimentWeekly.week_start).order_by(desc(SentimentWeekly.week_start)).limit(1)
                )
            ).scalar_one_or_none()
            if target_week is None:
                return {"week_start": None, "items": []}
        source_weights = {cfg.source_id: float(cfg.weight) for cfg in get_source_configs()}
        items = await build_theme_summary_for_week(
            session,
            week_start=target_week,
            source_weights=source_weights,
        )
    return {"week_start": str(target_week), "items": items}
