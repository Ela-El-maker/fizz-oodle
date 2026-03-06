from __future__ import annotations

from datetime import datetime, timedelta, timezone, date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.sentiment.types import MentionScore, RawPost, SentimentSourceConfig, WeeklyRow
from apps.core.models import (
    SentimentDigestReport,
    SentimentRawPost,
    SentimentTickerMention,
    SentimentWeekly,
    SourceHealth,
)


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
    return (await session.execute(select(SourceHealth).where(SourceHealth.source_id == source_id))).scalar_one_or_none()


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


async def mark_source_failure(
    session: AsyncSession,
    source_id: str,
    error: str,
    error_type: str | None,
    now_utc: datetime,
    fail_threshold: int,
    cooldown_minutes: int,
) -> None:
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
        blocked_inc=1 if (error_type or "") == "blocked" else 0,
    )
    merged.update({"error": error, "error_type": error_type or "unknown_error", "last_error_type": error_type or "unknown_error"})
    row.last_metrics = merged
    if row.consecutive_failures >= fail_threshold:
        row.breaker_state = "open"
        row.cooldown_until = now_utc + timedelta(minutes=cooldown_minutes)
    else:
        row.breaker_state = "closed"


async def upsert_raw_post(session: AsyncSession, post_id: str, post: RawPost) -> bool:
    existing = (
        await session.execute(select(SentimentRawPost).where(SentimentRawPost.post_id == post_id))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            SentimentRawPost(
                post_id=post_id,
                source_id=post.source_id,
                url=post.url,
                canonical_url=post.canonical_url,
                author=post.author,
                title=post.title,
                content=post.content,
                published_at=post.published_at,
                fetched_at=post.fetched_at,
                raw_payload=post.raw_payload,
            )
        )
        return True

    existing.fetched_at = post.fetched_at
    if not existing.content and post.content:
        existing.content = post.content
    return False


async def upsert_ticker_mention(session: AsyncSession, post_id: str, mention: MentionScore, source_id: str) -> bool:
    existing = (
        await session.execute(
            select(SentimentTickerMention).where(
                and_(
                    SentimentTickerMention.post_id == post_id,
                    SentimentTickerMention.ticker == mention.ticker,
                )
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            SentimentTickerMention(
                post_id=post_id,
                ticker=mention.ticker,
                company_name=mention.company_name,
                sentiment_score=mention.sentiment_score,
                sentiment_label=mention.sentiment_label,
                confidence=mention.confidence,
                source_weight=mention.source_weight,
                reasons={**mention.reasons, "source_id": source_id},
                model_version=mention.model_version,
                llm_used=mention.llm_used,
                scored_at=mention.scored_at,
            )
        )
        return True

    existing.sentiment_score = mention.sentiment_score
    existing.sentiment_label = mention.sentiment_label
    existing.confidence = mention.confidence
    existing.source_weight = mention.source_weight
    existing.reasons = {**mention.reasons, "source_id": source_id}
    existing.model_version = mention.model_version
    existing.llm_used = mention.llm_used
    existing.scored_at = mention.scored_at
    return False


async def fetch_mentions_for_window(session: AsyncSession, from_dt: datetime, to_dt: datetime) -> list[dict]:
    rows = (
        await session.execute(
            select(SentimentTickerMention, SentimentRawPost)
            .join(SentimentRawPost, SentimentTickerMention.post_id == SentimentRawPost.post_id)
            .where(
                and_(
                    (SentimentRawPost.published_at.is_(None) | (SentimentRawPost.published_at >= from_dt)),
                    (SentimentRawPost.published_at.is_(None) | (SentimentRawPost.published_at <= to_dt)),
                    SentimentRawPost.fetched_at >= from_dt - timedelta(days=1),
                )
            )
        )
    ).all()

    out: list[dict] = []
    for mention, raw in rows:
        payload = raw.raw_payload if isinstance(raw.raw_payload, dict) else {}
        engagement_raw = payload.get("engagement", 0)
        try:
            engagement = float(engagement_raw)
        except Exception:
            engagement = 0.0
        out.append(
            {
                "post_id": mention.post_id,
                "ticker": mention.ticker,
                "score": float(mention.sentiment_score),
                "label": mention.sentiment_label,
                "confidence": float(mention.confidence),
                "source_weight": float(mention.source_weight),
                "source_id": raw.source_id,
                "url": raw.url,
                "content": raw.content,
                "engagement": engagement,
            }
        )
    return out


async def fetch_prev_scores(session: AsyncSession, previous_week: date) -> dict[str, float]:
    rows = (
        await session.execute(select(SentimentWeekly.ticker, SentimentWeekly.bullish_pct).where(SentimentWeekly.week_start == previous_week))
    ).all()
    return {str(t): float(s) for t, s in rows}


async def upsert_weekly_rows(session: AsyncSession, rows: list[WeeklyRow]) -> int:
    inserted = 0
    for row in rows:
        existing = (
            await session.execute(
                select(SentimentWeekly).where(
                    and_(SentimentWeekly.week_start == row.week_start, SentimentWeekly.ticker == row.ticker)
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                SentimentWeekly(
                    week_start=row.week_start,
                    ticker=row.ticker,
                    company_name=row.company_name,
                    mentions_count=row.mentions_count,
                    bullish_count=row.bullish_count,
                    bearish_count=row.bearish_count,
                    neutral_count=row.neutral_count,
                    bullish_pct=row.bullish_pct,
                    bearish_pct=row.bearish_pct,
                    neutral_pct=row.neutral_pct,
                    weighted_score=row.weighted_score,
                    confidence=row.confidence,
                    top_sources=row.top_sources,
                    notable_quotes=row.notable_quotes,
                    wow_delta=row.wow_delta,
                    generated_at=row.generated_at,
                )
            )
            inserted += 1
        else:
            existing.company_name = row.company_name
            existing.mentions_count = row.mentions_count
            existing.bullish_count = row.bullish_count
            existing.bearish_count = row.bearish_count
            existing.neutral_count = row.neutral_count
            existing.bullish_pct = row.bullish_pct
            existing.bearish_pct = row.bearish_pct
            existing.neutral_pct = row.neutral_pct
            existing.weighted_score = row.weighted_score
            existing.confidence = row.confidence
            existing.top_sources = row.top_sources
            existing.notable_quotes = row.notable_quotes
            existing.wow_delta = row.wow_delta
            existing.generated_at = row.generated_at
    return inserted


async def get_digest(session: AsyncSession, week_start: date) -> SentimentDigestReport | None:
    return (
        await session.execute(select(SentimentDigestReport).where(SentimentDigestReport.week_start == week_start))
    ).scalar_one_or_none()


async def upsert_digest(
    session: AsyncSession,
    week_start: date,
    subject: str,
    html_content: str,
    payload_hash: str,
    status: str,
    metrics: dict,
    email_sent_at: datetime | None,
    email_error: str | None,
) -> SentimentDigestReport:
    row = await get_digest(session, week_start)
    if row is None:
        row = SentimentDigestReport(
            week_start=week_start,
            subject=subject,
            html_content=html_content,
            payload_hash=payload_hash,
            status=status,
            metrics=metrics,
            email_sent_at=email_sent_at,
            email_error=email_error,
        )
        session.add(row)
        return row

    row.generated_at = datetime.now(timezone.utc)
    row.status = status
    row.subject = subject
    row.html_content = html_content
    row.payload_hash = payload_hash
    row.metrics = metrics
    row.email_sent_at = email_sent_at
    row.email_error = email_error
    return row
