from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select

from apps.api.routers.auth import require_api_key
from apps.core.database import get_session
from apps.core.models import IndexDaily

router = APIRouter(tags=["index"], dependencies=[Depends(require_api_key)])


@router.get("/index/daily")
async def index_daily(date: date):
    async with get_session() as session:
        rows = (await session.execute(select(IndexDaily).where(IndexDaily.date == date))).scalars().all()

    return {
        "date": str(date),
        "items": [
            {
                "index_name": row.index_name,
                "value": float(row.value) if row.value is not None else None,
                "change_val": float(row.change_val) if row.change_val is not None else None,
                "pct_change": float(row.pct_change) if row.pct_change is not None else None,
                "source_id": row.source_id,
            }
            for row in rows
        ],
    }
