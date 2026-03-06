from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml
from apps.agents.announcements.sources.common import fetch_with_retries, parse_html_anchors
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.logger import get_logger
from apps.core.models import Company
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

settings = get_settings()
logger = get_logger(__name__)


def _resolve_cfg_path(path: str) -> Path:
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = (Path(__file__).resolve().parents[4] / path).resolve()
    return cfg_path


def _load_config_fallback_companies() -> list[SimpleNamespace]:
    companies: list[SimpleNamespace] = []

    company_ir_path = _resolve_cfg_path(settings.COMPANY_IR_CONFIG_PATH)
    if company_ir_path.exists():
        try:
            data = yaml.safe_load(company_ir_path.read_text(encoding="utf-8")) or {}
            for item in data.get("companies", []):
                ir_url = (item.get("ir_url") or "").strip()
                ticker = (item.get("ticker") or "").strip().upper()
                if not ir_url or not ticker:
                    continue
                companies.append(
                    SimpleNamespace(
                        ticker=ticker,
                        name=(item.get("company_name") or ticker).strip(),
                        ir_url=ir_url,
                    )
                )
        except Exception as exc:
            logger.warning("company_ir_fallback_config_error", error=str(exc), path=str(company_ir_path))

    if companies:
        return companies

    universe_path = _resolve_cfg_path(settings.UNIVERSE_CONFIG_PATH)
    if not universe_path.exists():
        return companies

    try:
        universe = yaml.safe_load(universe_path.read_text(encoding="utf-8")) or {}
        for item in universe.get("tracked_companies", []):
            ir_url = (item.get("ir_url") or "").strip()
            ticker = (item.get("ticker") or "").strip().upper()
            if not ir_url or not ticker:
                continue
            companies.append(
                SimpleNamespace(
                    ticker=ticker,
                    name=(item.get("company_name") or ticker).strip(),
                    ir_url=ir_url,
                )
            )
    except Exception as exc:
        logger.warning("company_ir_universe_fallback_error", error=str(exc), path=str(universe_path))

    return companies


async def collect(source: SourceConfig) -> list[RawAnnouncement]:
    out: list[RawAnnouncement] = []
    companies = []

    try:
        async with get_session() as session:
            companies = (
                await session.execute(
                    select(Company).where(Company.is_active.is_(True)).where(Company.ir_url.is_not(None))
                )
            ).scalars().all()
    except SQLAlchemyError as exc:
        # In strict DB-per-service mode, agent_b may run without the legacy `companies` table.
        logger.warning("company_ir_source_skipped", reason="companies_table_unavailable", error=str(exc))

    if not companies:
        companies = _load_config_fallback_companies()
        if companies:
            logger.info("company_ir_source_using_config_fallback", count=len(companies))
        else:
            logger.warning("company_ir_source_skipped", reason="no_companies_from_db_or_config")
            return []

    max_companies = max(1, int(settings.ANNOUNCEMENTS_COMPANY_IR_MAX_COMPANIES_PER_RUN))
    max_concurrency = max(1, int(settings.ANNOUNCEMENTS_COMPANY_IR_CONCURRENCY))
    selected = [company for company in companies if company.ir_url][:max_companies]
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _collect_company(company):
        async with semaphore:
            try:
                html = await fetch_with_retries(source, company.ir_url)
            except Exception:
                return []
            rows = parse_html_anchors(source, html)
            for row in rows:
                row.ticker_hint = company.ticker
                row.company_hint = company.name
            return rows

    batches = await asyncio.gather(*[_collect_company(company) for company in selected], return_exceptions=True)
    for batch in batches:
        if isinstance(batch, Exception):
            continue
        for row in batch:
            out.append(row)
            if len(out) >= settings.ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE:
                return out

    return out
