from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select

from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.models import SentimentWeekly

router = APIRouter(tags=["sentiment"], dependencies=[Depends(require_api_key)])


@router.get("/sentiment/latest")
async def latest_sentiment():
    async with get_session() as session:
        q = await session.execute(select(SentimentWeekly.week_start).order_by(desc(SentimentWeekly.week_start)).limit(1))
        week = q.scalar_one_or_none()
        if not week:
            return {"week_start": None, "items": []}

        rows = (
            await session.execute(
                select(SentimentWeekly)
                .where(SentimentWeekly.week_start == week)
                .order_by(SentimentWeekly.ticker.asc())
            )
        ).scalars().all()

        items = [
            {
                "ticker": row.ticker,
                "name": row.company_name,
                "bullish_pct": float(row.bullish_pct),
                "neutral_pct": float(row.neutral_pct),
                "bearish_pct": float(row.bearish_pct),
                "mentions": row.mentions_count,
                "score": float(row.weighted_score),
                "wow_delta": float(row.wow_delta) if row.wow_delta is not None else None,
                "confidence": float(row.confidence),
            }
            for row in rows
        ]

        return {"week_start": str(week), "items": items}
