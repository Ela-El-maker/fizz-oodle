from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select

from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.models import FxDaily

router = APIRouter(tags=["fx"], dependencies=[Depends(require_api_key)])


@router.get("/fx/daily")
async def fx_daily(date: date):
    async with get_session() as session:
        rows = (await session.execute(select(FxDaily).where(FxDaily.date == date).order_by(FxDaily.pair.asc()))).scalars().all()

    return {
        "date": str(date),
        "items": [
            {
                "pair": row.pair,
                "rate": float(row.rate),
                "source_id": row.source_id,
            }
            for row in rows
        ],
    }
