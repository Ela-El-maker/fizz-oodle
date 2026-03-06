from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.briefing.types import FxPoint, HeadlinePoint, IndexPoint, PricePoint
from apps.core.models import DailyBriefing, FxDaily, IndexDaily, NewsHeadlineDaily, PriceDaily


async def upsert_prices(session: AsyncSession, rows: list[PricePoint]) -> int:
    inserted = 0
    for row in rows:
        existing = (
            await session.execute(
                select(PriceDaily).where(
                    PriceDaily.date == row.date,
                    PriceDaily.ticker == row.ticker,
                    PriceDaily.source_id == row.source_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                PriceDaily(
                    date=row.date,
                    ticker=row.ticker,
                    close=row.close,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    volume=row.volume,
                    currency=row.currency,
                    source_id=row.source_id,
                    fetched_at=row.fetched_at,
                    raw_payload=row.raw_payload,
                )
            )
            inserted += 1
        else:
            existing.close = row.close
            existing.open = row.open
            existing.high = row.high
            existing.low = row.low
            existing.volume = row.volume
            existing.currency = row.currency
            existing.fetched_at = row.fetched_at
            existing.raw_payload = row.raw_payload
    return inserted


async def upsert_index(session: AsyncSession, rows: list[IndexPoint]) -> int:
    inserted = 0
    for row in rows:
        existing = (
            await session.execute(
                select(IndexDaily).where(
                    IndexDaily.date == row.date,
                    IndexDaily.index_name == row.index_name,
                    IndexDaily.source_id == row.source_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                IndexDaily(
                    date=row.date,
                    index_name=row.index_name,
                    value=row.value,
                    change_val=row.change_val,
                    pct_change=row.pct_change,
                    source_id=row.source_id,
                    fetched_at=row.fetched_at,
                    raw_payload=row.raw_payload,
                )
            )
            inserted += 1
        else:
            existing.value = row.value
            existing.change_val = row.change_val
            existing.pct_change = row.pct_change
            existing.fetched_at = row.fetched_at
            existing.raw_payload = row.raw_payload
    return inserted


async def upsert_fx(session: AsyncSession, rows: list[FxPoint]) -> int:
    inserted = 0
    for row in rows:
        existing = (
            await session.execute(
                select(FxDaily).where(
                    FxDaily.date == row.date,
                    FxDaily.pair == row.pair,
                    FxDaily.source_id == row.source_id,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                FxDaily(
                    date=row.date,
                    pair=row.pair,
                    rate=row.rate,
                    source_id=row.source_id,
                    fetched_at=row.fetched_at,
                    raw_payload=row.raw_payload,
                )
            )
            inserted += 1
        else:
            existing.rate = row.rate
            existing.fetched_at = row.fetched_at
            existing.raw_payload = row.raw_payload
    return inserted


async def upsert_headlines(session: AsyncSession, rows: list[HeadlinePoint]) -> int:
    inserted = 0
    for row in rows:
        existing = (
            await session.execute(
                select(NewsHeadlineDaily).where(
                    NewsHeadlineDaily.date == row.date,
                    NewsHeadlineDaily.source_id == row.source_id,
                    NewsHeadlineDaily.url == row.url,
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                NewsHeadlineDaily(
                    date=row.date,
                    source_id=row.source_id,
                    headline=row.headline,
                    url=row.url,
                    published_at=row.published_at,
                    fetched_at=row.fetched_at,
                )
            )
            inserted += 1
        else:
            existing.headline = row.headline
            existing.published_at = row.published_at
            existing.fetched_at = row.fetched_at
    return inserted


async def upsert_daily_briefing(
    session: AsyncSession,
    briefing_date,
    subject: str,
    html_content: str,
    payload_hash: str,
    status: str,
    metrics: dict,
    email_sent_at: datetime | None,
    email_error: str | None,
) -> DailyBriefing:
    existing = (
        await session.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date))
    ).scalar_one_or_none()

    if existing is None:
        row = DailyBriefing(
            briefing_date=briefing_date,
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

    existing.generated_at = datetime.utcnow()
    existing.subject = subject
    existing.html_content = html_content
    existing.payload_hash = payload_hash
    existing.status = status
    existing.metrics = metrics
    existing.email_sent_at = email_sent_at
    existing.email_error = email_error
    return existing
