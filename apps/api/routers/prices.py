from __future__ import annotations

from datetime import date
from pathlib import Path
from collections import Counter
import yaml

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from apps.api.routers.auth import require_api_key
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.models import PriceSnapshot, Company, PriceDaily

router = APIRouter(tags=["prices"], dependencies=[Depends(require_api_key)])
settings = get_settings()


def _resolve_config_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    # repo root is .../apps/api/routers -> parents[3]
    return Path(__file__).resolve().parents[3] / path


def _load_universe_rows() -> list[dict]:
    config_path = _resolve_config_path(settings.UNIVERSE_CONFIG_PATH)
    if not config_path.exists():
        return []
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    rows = data.get("tracked_companies", []) or []
    return [row for row in rows if isinstance(row, dict) and str(row.get("ticker", "")).strip()]


@router.get("/universe/summary")
async def universe_summary():
    rows = _load_universe_rows()
    tickers = sorted({str(row.get("ticker", "")).strip().upper() for row in rows if str(row.get("ticker", "")).strip()})
    exchange_counts = Counter(str(row.get("exchange", "UNKNOWN")).strip().upper() or "UNKNOWN" for row in rows)
    sector_counts = Counter(str(row.get("sector", "other")).strip().lower() or "other" for row in rows)

    return {
        "tracked_companies": len(rows),
        "tracked_tickers": len(tickers),
        "nse_tickers": int(exchange_counts.get("NSE", 0)),
        "exchanges": dict(exchange_counts),
        "sectors": dict(sector_counts),
        "tickers": tickers,
    }


@router.get("/prices/latest")
async def latest_prices():
    async with get_session() as session:
        # find latest snapshot_date
        q = await session.execute(select(PriceSnapshot.snapshot_date).order_by(PriceSnapshot.snapshot_date.desc()).limit(1))
        latest: date | None = q.scalar_one_or_none()
        if not latest:
            return {"date": None, "items": []}

        rows = await session.execute(
            select(Company.ticker, Company.name, PriceSnapshot.price, PriceSnapshot.pct_change)
            .join(PriceSnapshot, PriceSnapshot.company_id == Company.id)
            .where(PriceSnapshot.snapshot_date == latest)
            .order_by(Company.exchange, Company.ticker)
        )

        items = [
            {"ticker": t, "name": n, "price": float(p) if p is not None else None, "pct_change": float(pc) if pc is not None else None}
            for (t, n, p, pc) in rows.all()
        ]
        return {"date": str(latest), "items": items}


@router.get("/prices/daily")
async def prices_daily(date: date):
    async with get_session() as session:
        rows = (
            await session.execute(
                select(PriceDaily).where(PriceDaily.date == date).order_by(PriceDaily.ticker.asc())
            )
        ).scalars().all()

    return {
        "date": str(date),
        "items": [
            {
                "ticker": row.ticker,
                "close": float(row.close) if row.close is not None else None,
                "open": float(row.open) if row.open is not None else None,
                "high": float(row.high) if row.high is not None else None,
                "low": float(row.low) if row.low is not None else None,
                "volume": float(row.volume) if row.volume is not None else None,
                "currency": row.currency,
                "source_id": row.source_id,
            }
            for row in rows
        ],
    }


@router.get("/prices/{ticker}")
async def prices_for_ticker(
    ticker: str,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
):
    t = ticker.upper()
    async with get_session() as session:
        stmt = select(PriceDaily).where(PriceDaily.ticker == t).order_by(PriceDaily.date.desc())
        if from_date:
            stmt = stmt.where(PriceDaily.date >= from_date)
        if to_date:
            stmt = stmt.where(PriceDaily.date <= to_date)
        rows = (await session.execute(stmt)).scalars().all()

    return {
        "ticker": t,
        "items": [
            {
                "date": str(row.date),
                "close": float(row.close) if row.close is not None else None,
                "open": float(row.open) if row.open is not None else None,
                "high": float(row.high) if row.high is not None else None,
                "low": float(row.low) if row.low is not None else None,
                "volume": float(row.volume) if row.volume is not None else None,
                "currency": row.currency,
                "source_id": row.source_id,
            }
            for row in rows
        ],
    }
