from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from apps.core.database import get_session
from apps.core.logger import get_logger
from apps.core.models import Company

logger = get_logger(__name__)

TRACKED_COMPANIES = [
    # NSE-listed (15)
    ("SCOM", "Safaricom", "NSE", "Kenya", "KES"),
    ("KCB", "KCB Group", "NSE", "Kenya", "KES"),
    ("EQTY", "Equity Bank", "NSE", "Kenya", "KES"),
    ("EABL", "EABL", "NSE", "Kenya", "KES"),
    ("COOP", "Co-operative Bank", "NSE", "Kenya", "KES"),
    ("BAT", "BAT Kenya", "NSE", "Kenya", "KES"),
    ("NMG", "Nation Media", "NSE", "Kenya", "KES"),
    ("BAMB", "Bamburi", "NSE", "Kenya", "KES"),
    ("SBIC", "Stanbic Holdings", "NSE", "Kenya", "KES"),
    ("DTK", "Diamond Trust Bank", "NSE", "Kenya", "KES"),
    ("JUB", "Jubilee Holdings", "NSE", "Kenya", "KES"),
    ("KQ", "Kenya Airways", "NSE", "Kenya", "KES"),
    ("ABSA", "Absa Kenya", "NSE", "Kenya", "KES"),
    ("NCBA", "NCBA Group", "NSE", "Kenya", "KES"),
    ("SCBK", "Standard Chartered Kenya", "NSE", "Kenya", "KES"),
    # Pan-African (5)
    ("MTN", "MTN Group", "JSE", "South Africa", "ZAR"),
    ("NPN", "Naspers", "JSE", "South Africa", "ZAR"),
    ("SBK", "Standard Bank Group", "JSE", "South Africa", "ZAR"),
    ("DANGCEM", "Dangote Cement", "NGX", "Nigeria", "NGN"),
    ("ZENITHBANK", "Zenith Bank", "NGX", "Nigeria", "NGN"),
]


async def seed_companies() -> None:
    try:
        async with get_session() as session:
            # quick check
            res = await session.execute(select(Company.id).limit(1))
            if res.scalar_one_or_none() is not None:
                return

            for ticker, name, exchange, country, currency in TRACKED_COMPANIES:
                session.add(Company(ticker=ticker, name=name, exchange=exchange, country=country, currency=currency))

            await session.commit()
    except SQLAlchemyError as exc:
        # In strict microservice mode, some service-owned databases may not include
        # the shared `companies` table. Pipelines should continue with config-based maps.
        logger.warning("seed_companies_skipped", error=str(exc))
