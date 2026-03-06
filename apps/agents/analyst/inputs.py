from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.analyst.types import InputsBundle, MarketMover
from apps.core.config import get_settings
from apps.core.logger import get_logger
from apps.core.models import (
    ArchiveRun,
    Announcement,
    DailyBriefing,
    FxDaily,
    ImpactStat,
    IndexDaily,
    Pattern,
    PriceDaily,
    SentimentDigestReport,
    SentimentWeekly,
)

settings = get_settings()
logger = get_logger(__name__)

EAT = ZoneInfo("Africa/Nairobi")
_BRIEFING_FRESHNESS_HOURS = 24
_ANNOUNCEMENT_FRESHNESS_HOURS = 6


def resolve_period_key(report_type: str, period_key: date | None = None) -> date:
    if period_key is not None:
        return period_key

    now_eat = datetime.now(EAT).date()
    if report_type == "weekly":
        return now_eat - timedelta(days=now_eat.weekday())
    return now_eat


def _build_price_history_map(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        row_date = row.get("date")
        out[ticker].append(
            {
                "date": str(row_date) if row_date is not None else None,
                "close": float(row.get("close")) if row.get("close") is not None else None,
                "volume": float(row.get("volume")) if row.get("volume") is not None else None,
            }
        )
    for ticker in list(out.keys()):
        out[ticker] = sorted(out[ticker], key=lambda r: str(r.get("date") or ""))[-5:]
    return dict(out)


def _extract_calibration_feedback(archivist_feedback: dict | None) -> dict | None:
    if not archivist_feedback:
        return None
    archive = archivist_feedback.get("archive_latest_weekly") or {}
    summary = archive.get("summary") if isinstance(archive, dict) else None
    if not isinstance(summary, dict):
        return None
    accuracy_rows = summary.get("accuracy") or []
    if not isinstance(accuracy_rows, list):
        return None

    analyst_rows = [
        row
        for row in accuracy_rows
        if isinstance(row, dict)
        and str(row.get("agent_name") or "").strip().lower() == "analyst"
        and str(row.get("ticker") or "").strip().upper() == "MARKET"
    ]
    if not analyst_rows:
        return None

    latest = analyst_rows[0]
    actual = float(latest.get("accuracy_pct") or 0.0)
    return {
        "nominal_target_pct": 80.0,
        "actual_accuracy_pct": actual,
        "sample_count": int(latest.get("sample_count") or 0),
        "grade": str(latest.get("grade") or ""),
    }


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


async def _get_market_date(session: AsyncSession, report_type: str, period_key: date) -> date | None:
    if report_type == "weekly":
        window_end = period_key + timedelta(days=6)
        stmt = (
            select(PriceDaily.date)
            .where(PriceDaily.date <= window_end)
            .order_by(desc(PriceDaily.date))
            .limit(1)
        )
    else:
        stmt = (
            select(PriceDaily.date)
            .where(PriceDaily.date <= period_key)
            .order_by(desc(PriceDaily.date))
            .limit(1)
        )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _get_briefing(session: AsyncSession, market_date: date | None) -> DailyBriefing | None:
    if market_date is None:
        return None

    row = (
        await session.execute(
            select(DailyBriefing)
            .where(DailyBriefing.briefing_date == market_date)
            .limit(1)
        )
    ).scalars().first()
    if row is not None:
        return row

    return (
        await session.execute(
            select(DailyBriefing)
            .where(DailyBriefing.briefing_date <= market_date)
            .order_by(desc(DailyBriefing.briefing_date))
            .limit(1)
        )
    ).scalars().first()


def _announcement_window(report_type: str, period_key: date) -> tuple[datetime, datetime]:
    if report_type == "weekly":
        start_eat = datetime.combine(period_key, time.min, tzinfo=EAT)
        end_eat = start_eat + timedelta(days=7)
    else:
        lookback = int(settings.ANALYST_LOOKBACK_DAYS)
        start_eat = datetime.combine(period_key, time.min, tzinfo=EAT) - timedelta(days=lookback)
        end_eat = datetime.combine(period_key + timedelta(days=1), time.min, tzinfo=EAT)

    return start_eat.astimezone(timezone.utc), end_eat.astimezone(timezone.utc)


async def _get_announcements(
    session: AsyncSession,
    report_type: str,
    period_key: date,
) -> list[Announcement]:
    start_utc, end_utc = _announcement_window(report_type, period_key)
    stmt = (
        select(Announcement)
        .where(and_(Announcement.first_seen_at >= start_utc, Announcement.first_seen_at < end_utc))
        .order_by(Announcement.first_seen_at.desc())
        .limit(int(settings.ANALYST_MAX_EVENTS))
    )
    return (await session.execute(stmt)).scalars().all()


async def _get_sentiment_context(session: AsyncSession) -> tuple[date | None, list[SentimentWeekly], str | None]:
    week = (
        await session.execute(
            select(SentimentDigestReport.week_start)
            .where(SentimentDigestReport.status == "sent")
            .order_by(desc(SentimentDigestReport.week_start))
            .limit(1)
        )
    ).scalar_one_or_none()

    source_status: str | None = "sent"
    if week is None:
        digest = (
            await session.execute(select(SentimentDigestReport).order_by(desc(SentimentDigestReport.week_start)).limit(1))
        ).scalars().first()
        if digest is not None:
            week = digest.week_start
            source_status = digest.status

    if week is None:
        week = (
            await session.execute(select(SentimentWeekly.week_start).order_by(desc(SentimentWeekly.week_start)).limit(1))
        ).scalar_one_or_none()
        if week is not None:
            source_status = "weekly_only"

    if week is None:
        return None, [], None

    rows = (
        await session.execute(
            select(SentimentWeekly)
            .where(SentimentWeekly.week_start == week)
            .order_by(SentimentWeekly.ticker.asc())
        )
    ).scalars().all()

    return week, rows, source_status


async def _build_movers(session: AsyncSession, market_date: date | None) -> tuple[list[MarketMover], list[MarketMover]]:
    if market_date is None:
        return [], []

    today_rows = (
        await session.execute(select(PriceDaily).where(PriceDaily.date == market_date).order_by(PriceDaily.ticker.asc()))
    ).scalars().all()

    movers: list[MarketMover] = []
    for row in today_rows:
        close = float(row.close) if row.close is not None else None
        prev = (
            await session.execute(
                select(PriceDaily)
                .where(and_(PriceDaily.ticker == row.ticker, PriceDaily.date < market_date))
                .order_by(desc(PriceDaily.date))
                .limit(1)
            )
        ).scalars().first()
        prev_close = float(prev.close) if prev and prev.close is not None else None
        pct_change = None
        if close is not None and prev_close not in (None, 0):
            pct_change = round(((close - prev_close) / prev_close) * 100.0, 3)
        movers.append(MarketMover(ticker=row.ticker, close=close, pct_change=pct_change))

    with_pct = [m for m in movers if m.pct_change is not None]
    gainers = sorted(with_pct, key=lambda m: float(m.pct_change or -9999), reverse=True)[:5]
    losers = sorted(with_pct, key=lambda m: float(m.pct_change or 9999))[:5]
    return gainers, losers


async def _build_price_history_db(
    session: AsyncSession,
    *,
    market_date: date | None,
    tickers: list[str],
) -> dict[str, list[dict]]:
    if market_date is None or not tickers:
        return {}
    lookback_start = market_date - timedelta(days=14)
    rows = (
        await session.execute(
            select(PriceDaily)
            .where(PriceDaily.ticker.in_(tickers))
            .where(PriceDaily.date >= lookback_start)
            .where(PriceDaily.date <= market_date)
            .order_by(PriceDaily.ticker.asc(), PriceDaily.date.asc())
        )
    ).scalars().all()
    compact = [
        {
            "ticker": row.ticker,
            "date": row.date,
            "close": float(row.close) if row.close is not None else None,
            "volume": float(row.volume) if row.volume is not None else None,
        }
        for row in rows
    ]
    return _build_price_history_map(compact)


async def load_inputs(
    session: AsyncSession,
    report_type: str,
    period_key: date,
) -> InputsBundle:
    try:
        db_bundle = await _load_inputs_from_db(session=session, report_type=report_type, period_key=period_key)
    except SQLAlchemyError as exc:
        logger.warning("analyst_db_inputs_unavailable", error=str(exc))
        await session.rollback()
        db_bundle = InputsBundle(
            report_type=report_type,
            period_key=period_key,
            market_date=None,
            briefing=None,
            announcements=[],
            sentiment_rows=[],
            index_rows=[],
            fx_rows=[],
            movers=[],
            losers=[],
            price_history={},
            global_theme_summary=[],
            archivist_feedback=None,
            calibration_feedback=None,
            degraded_reasons=["db_snapshot_unavailable"],
            inputs_summary={
                "briefing": {"available": False, "briefing_date": None, "status": None},
                "announcements": {"available": False, "count": 0},
                "sentiment": {"available": False, "week_start": None, "status": None, "rows": 0},
                "archivist_feedback": {"available": False, "patterns": 0, "impacts": 0},
                "market_date": None,
                "db_snapshot_available": False,
            },
            upstream_quality={},
        )
    needs_fallback = settings.ANALYST_USE_INTERNAL_APIS or _bundle_needs_fallback(db_bundle)
    if not needs_fallback:
        db_bundle.upstream_quality = _compute_upstream_quality(db_bundle)
        return db_bundle

    api_bundle = await _load_inputs_from_services(report_type=report_type, period_key=period_key)
    merged = _merge_bundles(db_bundle, api_bundle)
    merged.upstream_quality = _compute_upstream_quality(merged)
    return merged


def _bundle_needs_fallback(bundle: InputsBundle) -> bool:
    if bundle.briefing is None:
        return True
    if not bundle.announcements:
        return True
    if not bundle.sentiment_rows:
        return True
    if not bundle.index_rows or not bundle.fx_rows:
        return True
    if settings.ANALYST_USE_ARCHIVIST_FEEDBACK and not bundle.archivist_feedback:
        return True
    return False


def _merge_bundles(primary: InputsBundle, fallback: InputsBundle) -> InputsBundle:
    briefing = primary.briefing or fallback.briefing
    announcements = primary.announcements or fallback.announcements
    sentiment_rows = primary.sentiment_rows or fallback.sentiment_rows
    index_rows = primary.index_rows or fallback.index_rows
    fx_rows = primary.fx_rows or fallback.fx_rows
    movers = primary.movers or fallback.movers
    losers = primary.losers or fallback.losers
    price_history = primary.price_history or fallback.price_history
    global_theme_summary = primary.global_theme_summary or fallback.global_theme_summary
    archivist_feedback = primary.archivist_feedback or fallback.archivist_feedback
    calibration_feedback = primary.calibration_feedback or fallback.calibration_feedback

    reasons = set(primary.degraded_reasons) | set(fallback.degraded_reasons)
    if briefing is not None:
        reasons.discard("briefing_missing")
        reasons.discard("briefing_api_unavailable")
    if announcements:
        reasons.discard("announcements_unavailable")
    if sentiment_rows:
        reasons.discard("sentiment_week_missing")
    if movers or losers:
        reasons.discard("movers_unavailable")
    if archivist_feedback:
        reasons.discard("archivist_feedback_unavailable")
    elif not settings.ANALYST_USE_ARCHIVIST_FEEDBACK:
        reasons.discard("archivist_feedback_unavailable")
    if index_rows:
        reasons.discard("index_unavailable")
    if fx_rows:
        reasons.discard("fx_unavailable")
    if primary.market_date is not None or fallback.market_date is not None:
        reasons.discard("price_data_missing")
    if briefing and announcements and sentiment_rows and index_rows and fx_rows:
        reasons.discard("db_snapshot_unavailable")

    merged_summary = dict(primary.inputs_summary or {})
    for key, value in (fallback.inputs_summary or {}).items():
        if key not in merged_summary or not merged_summary.get(key):
            merged_summary[key] = value
    merged_summary["fallback_used"] = True

    return InputsBundle(
        report_type=primary.report_type,
        period_key=primary.period_key,
        market_date=primary.market_date or fallback.market_date,
        briefing=briefing,
        announcements=announcements,
        sentiment_rows=sentiment_rows,
        index_rows=index_rows,
        fx_rows=fx_rows,
        movers=movers,
        losers=losers,
        price_history=price_history,
        global_theme_summary=global_theme_summary,
        archivist_feedback=archivist_feedback,
        calibration_feedback=calibration_feedback,
        degraded_reasons=sorted(reasons),
        inputs_summary=merged_summary,
    )


def _compute_upstream_quality(bundle: InputsBundle) -> dict:
    now_eat = datetime.now(EAT)
    expected_sentiment_week = now_eat.date() - timedelta(days=now_eat.date().weekday())

    availability_checks = {
        "briefing": bool(bundle.briefing),
        "announcements": bool(bundle.announcements),
        "sentiment": bool(bundle.sentiment_rows),
        "index": bool(bundle.index_rows),
        "fx": bool(bundle.fx_rows),
    }
    availability_pct = round((sum(1 for ok in availability_checks.values() if ok) / len(availability_checks)) * 100.0, 2)

    freshness_checks: dict[str, bool] = {}
    if bundle.market_date is not None:
        market_dt = datetime.combine(bundle.market_date, time.min, tzinfo=EAT)
        freshness_checks["briefing_within_24h"] = (now_eat - market_dt) <= timedelta(hours=_BRIEFING_FRESHNESS_HOURS)
        freshness_checks["announcements_within_6h"] = (now_eat - market_dt) <= timedelta(hours=_ANNOUNCEMENT_FRESHNESS_HOURS)
    else:
        freshness_checks["briefing_within_24h"] = False
        freshness_checks["announcements_within_6h"] = False

    sentiment_week = _parse_iso_date((bundle.inputs_summary.get("sentiment") or {}).get("week_start"))
    freshness_checks["sentiment_week_matches"] = sentiment_week == expected_sentiment_week if sentiment_week else False

    freshness_pass_pct = round((sum(1 for ok in freshness_checks.values() if ok) / len(freshness_checks)) * 100.0, 2)
    degradation_count = len(bundle.degraded_reasons)
    coverage_pct = round(
        (
            min(100.0, (len(bundle.announcements) / max(1, int(settings.ANALYST_MAX_EVENTS))) * 100.0) * 0.5
            + min(100.0, (len(bundle.sentiment_rows) / 20.0) * 100.0) * 0.3
            + min(100.0, (len(bundle.movers) + len(bundle.losers)) / 10.0 * 100.0) * 0.2
        ),
        2,
    )
    score = round(max(0.0, min(100.0, (availability_pct * 0.5) + (freshness_pass_pct * 0.3) + (coverage_pct * 0.2) - (degradation_count * 5.0))), 2)

    return {
        "availability_checks": availability_checks,
        "availability_pct": availability_pct,
        "freshness_checks": freshness_checks,
        "freshness_pct": freshness_pass_pct,
        "coverage_pct": coverage_pct,
        "degradation_count": degradation_count,
        "score": score,
    }


async def _load_inputs_from_services(report_type: str, period_key: date) -> InputsBundle:
    degraded_reasons: list[str] = []
    headers = {"X-API-Key": settings.API_KEY}
    internal_headers = {"X-Internal-Api-Key": settings.INTERNAL_API_KEY}
    timeout = 20.0

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Agent A market context
        market_date = period_key
        briefing_item = None
        try:
            if report_type == "daily":
                resp = await client.get(f"{settings.AGENT_A_SERVICE_URL}/briefings/daily", params={"date": period_key.isoformat()}, headers=headers)
                if 200 <= resp.status_code < 300:
                    briefing_item = (resp.json() or {}).get("item")
                else:
                    # fall back to latest
                    latest = await client.get(f"{settings.AGENT_A_SERVICE_URL}/briefings/latest", headers=headers)
                    if 200 <= latest.status_code < 300:
                        briefing_item = (latest.json() or {}).get("item")
            else:
                latest = await client.get(f"{settings.AGENT_A_SERVICE_URL}/briefings/latest", headers=headers)
                if 200 <= latest.status_code < 300:
                    briefing_item = (latest.json() or {}).get("item")
            if briefing_item and briefing_item.get("briefing_date"):
                market_date = date.fromisoformat(briefing_item["briefing_date"])
        except Exception:
            degraded_reasons.append("briefing_api_unavailable")

        if briefing_item is None:
            degraded_reasons.append("briefing_missing")

        price_items = []
        index_items = []
        fx_items = []
        price_history: dict[str, list[dict]] = {}
        try:
            pr = await client.get(f"{settings.AGENT_A_SERVICE_URL}/prices/daily", params={"date": market_date.isoformat()}, headers=headers)
            if 200 <= pr.status_code < 300:
                price_items = (pr.json() or {}).get("items") or []
            else:
                degraded_reasons.append("price_data_missing")
        except Exception:
            degraded_reasons.append("price_data_missing")

        try:
            ir = await client.get(f"{settings.AGENT_A_SERVICE_URL}/index/daily", params={"date": market_date.isoformat()}, headers=headers)
            if 200 <= ir.status_code < 300:
                index_items = (ir.json() or {}).get("items") or []
            else:
                degraded_reasons.append("index_unavailable")
        except Exception:
            degraded_reasons.append("index_unavailable")

        try:
            fr = await client.get(f"{settings.AGENT_A_SERVICE_URL}/fx/daily", params={"date": market_date.isoformat()}, headers=headers)
            if 200 <= fr.status_code < 300:
                fx_items = (fr.json() or {}).get("items") or []
            else:
                degraded_reasons.append("fx_unavailable")
        except Exception:
            degraded_reasons.append("fx_unavailable")

        # Per-ticker 5-day history for convergence inputs.
        try:
            for row in price_items:
                ticker = str(row.get("ticker") or "").upper().strip()
                if not ticker:
                    continue
                hist = await client.get(
                    f"{settings.AGENT_A_SERVICE_URL}/prices/{ticker}",
                    params={
                        "from": (market_date - timedelta(days=14)).isoformat(),
                        "to": market_date.isoformat(),
                    },
                    headers=headers,
                )
                if 200 <= hist.status_code < 300:
                    history_items = (hist.json() or {}).get("items") or []
                    normalized_hist = [
                        {
                            "ticker": ticker,
                            "date": h.get("date"),
                            "close": h.get("close"),
                            "volume": h.get("volume"),
                        }
                        for h in history_items
                    ]
                    if normalized_hist:
                        price_history[ticker] = _build_price_history_map(normalized_hist).get(ticker, [])
        except Exception:
            # Non-blocking for analyst synthesis.
            degraded_reasons.append("price_history_unavailable")

        # Agent B announcements
        start_utc, end_utc = _announcement_window(report_type, period_key)
        ann_items = []
        try:
            ar = await client.get(
                f"{settings.AGENT_B_SERVICE_URL}/announcements",
                params={
                    "from": start_utc.isoformat(),
                    "to": end_utc.isoformat(),
                    "limit": int(settings.ANALYST_MAX_EVENTS),
                },
                headers=headers,
            )
            if 200 <= ar.status_code < 300:
                ann_items = (ar.json() or {}).get("items") or []
            else:
                degraded_reasons.append("announcements_unavailable")
        except Exception:
            degraded_reasons.append("announcements_unavailable")

        # Agent C sentiment
        sentiment_rows = []
        sentiment_week = None
        sentiment_status = None
        try:
            dr = await client.get(f"{settings.AGENT_C_SERVICE_URL}/sentiment/digest/latest", headers=headers)
            if 200 <= dr.status_code < 300:
                digest_item = (dr.json() or {}).get("item")
                if digest_item:
                    sentiment_week = date.fromisoformat(digest_item["week_start"])
                    sentiment_status = digest_item.get("status")
            if sentiment_week:
                wr = await client.get(
                    f"{settings.AGENT_C_SERVICE_URL}/sentiment/weekly",
                    params={"week_start": sentiment_week.isoformat(), "limit": 200, "offset": 0},
                    headers=headers,
                )
                if 200 <= wr.status_code < 300:
                    sentiment_rows = (wr.json() or {}).get("items") or []
        except Exception:
            pass

        if sentiment_week is None:
            degraded_reasons.append("sentiment_week_missing")
        elif sentiment_status != "sent":
            degraded_reasons.append("sentiment_week_not_sent")

        archivist_feedback: dict | None = None
        if settings.ANALYST_USE_ARCHIVIST_FEEDBACK:
            try:
                er = await client.get(
                    f"{settings.AGENT_E_SERVICE_URL}/internal/data/latest",
                    headers=internal_headers,
                )
                if 200 <= er.status_code < 300:
                    data = er.json() or {}
                    archivist_feedback = {
                        "patterns": data.get("patterns") or [],
                        "impacts": data.get("impacts") or [],
                        "archive_latest_weekly": data.get("archive_latest_weekly"),
                    }
                else:
                    degraded_reasons.append("archivist_feedback_unavailable")
            except Exception:
                degraded_reasons.append("archivist_feedback_unavailable")

        calibration_feedback = _extract_calibration_feedback(archivist_feedback)

    movers: list[MarketMover] = []
    for row in price_items:
        close = row.get("close")
        pct_change = row.get("pct_change")
        movers.append(MarketMover(ticker=str(row.get("ticker") or ""), close=float(close) if close is not None else None, pct_change=float(pct_change) if pct_change is not None else None))
    with_pct = [m for m in movers if m.pct_change is not None]
    gainers = sorted(with_pct, key=lambda m: float(m.pct_change or -9999), reverse=True)[:5]
    losers = sorted(with_pct, key=lambda m: float(m.pct_change or 9999))[:5]

    inputs_summary = {
        "briefing": {
            "available": briefing_item is not None,
            "briefing_date": briefing_item.get("briefing_date") if briefing_item else None,
            "status": briefing_item.get("status") if briefing_item else None,
        },
        "announcements": {"available": True, "count": len(ann_items)},
        "sentiment": {
            "available": bool(sentiment_rows),
            "week_start": str(sentiment_week) if sentiment_week else None,
            "status": sentiment_status,
            "rows": len(sentiment_rows),
        },
        "archivist_feedback": {
            "available": bool(archivist_feedback),
            "patterns": len((archivist_feedback or {}).get("patterns") or []),
            "impacts": len((archivist_feedback or {}).get("impacts") or []),
        },
        "market_date": market_date.isoformat(),
        "movers": {
            "available": bool(gainers or losers),
            "gainers_count": len(gainers),
            "losers_count": len(losers),
        },
    }
    global_theme_summary = []
    briefing_metrics = (briefing_item or {}).get("metrics") if isinstance(briefing_item, dict) else {}
    if isinstance(briefing_metrics, dict):
        raw_themes = briefing_metrics.get("global_themes")
        if isinstance(raw_themes, list):
            global_theme_summary = [row for row in raw_themes if isinstance(row, dict)]

    return InputsBundle(
        report_type=report_type,
        period_key=period_key,
        market_date=market_date,
        briefing=briefing_item,
        announcements=[
            {
                "announcement_id": row.get("announcement_id"),
                "ticker": row.get("ticker"),
                "type": row.get("announcement_type"),
                "headline": row.get("headline"),
                "url": row.get("url"),
                "date": row.get("announcement_date"),
                "source_id": row.get("source_id"),
                "type_confidence": float(row.get("type_confidence") or 0.0),
                "severity": row.get("severity"),
                "alpha_context": row.get("alpha_context"),
                "first_seen_at": row.get("first_seen_at"),
                "scope": row.get("scope"),
                "theme": row.get("theme"),
                "signal_class": row.get("signal_class"),
                "kenya_impact_score": row.get("kenya_impact_score"),
                "affected_sectors": row.get("affected_sectors") or [],
                "transmission_channels": row.get("transmission_channels") or [],
            }
            for row in ann_items
        ],
        sentiment_rows=[
            {
                "ticker": row.get("ticker"),
                "company_name": row.get("company_name"),
                "mentions_count": int(row.get("mentions_count") or 0),
                "bullish_pct": float(row.get("bullish_pct") or 0.0),
                "bearish_pct": float(row.get("bearish_pct") or 0.0),
                "neutral_pct": float(row.get("neutral_pct") or 0.0),
                "weighted_score": float(row.get("weighted_score") or 0.0),
                "confidence": float(row.get("confidence") or 0.0),
                "wow_delta": float(row.get("wow_delta")) if row.get("wow_delta") is not None else None,
                "notable_quotes": row.get("notable_quotes") or [],
                "top_sources": row.get("top_sources") or {},
            }
            for row in sentiment_rows
        ],
        index_rows=index_items,
        fx_rows=fx_items,
        movers=gainers,
        losers=losers,
        price_history=price_history,
        global_theme_summary=global_theme_summary,
        archivist_feedback=archivist_feedback,
        calibration_feedback=calibration_feedback,
        degraded_reasons=sorted(set(degraded_reasons)),
        inputs_summary=inputs_summary,
        upstream_quality={},
    )


async def _load_inputs_from_db(
    session: AsyncSession,
    report_type: str,
    period_key: date,
) -> InputsBundle:
    degraded_reasons: list[str] = []
    market_date = await _get_market_date(session, report_type=report_type, period_key=period_key)
    if market_date is None:
        degraded_reasons.append("price_data_missing")

    briefing_row = await _get_briefing(session, market_date)
    if briefing_row is None:
        degraded_reasons.append("briefing_missing")

    announcements = await _get_announcements(session, report_type=report_type, period_key=period_key)

    sentiment_week, sentiment_rows, sentiment_status = await _get_sentiment_context(session)
    if sentiment_week is None:
        degraded_reasons.append("sentiment_week_missing")
    elif sentiment_status != "sent":
        degraded_reasons.append("sentiment_week_not_sent")

    gainers, losers = await _build_movers(session, market_date)

    index_rows = []
    fx_rows = []
    price_history: dict[str, list[dict]] = {}
    archivist_feedback: dict | None = None
    calibration_feedback: dict | None = None
    if market_date is not None:
        index_rows = (
            await session.execute(
                select(IndexDaily).where(IndexDaily.date == market_date).order_by(IndexDaily.index_name.asc())
            )
        ).scalars().all()
        fx_rows = (
            await session.execute(select(FxDaily).where(FxDaily.date == market_date).order_by(FxDaily.pair.asc()))
        ).scalars().all()
        history_tickers = sorted({m.ticker for m in gainers + losers if m.ticker})
        price_history = await _build_price_history_db(
            session,
            market_date=market_date,
            tickers=history_tickers,
        )

    if settings.ANALYST_USE_ARCHIVIST_FEEDBACK:
        active_patterns = (
            await session.execute(
                select(Pattern)
                .where(and_(Pattern.active.is_(True), Pattern.status == "confirmed"))
                .order_by(Pattern.accuracy_pct.desc(), Pattern.updated_at.desc())
                .limit(10)
            )
        ).scalars().all()
        impacts = (
            await session.execute(
                select(ImpactStat).order_by(ImpactStat.period_key.desc()).limit(10)
            )
        ).scalars().all()
        archive_latest = (
            await session.execute(
                select(ArchiveRun).where(ArchiveRun.run_type == "weekly").order_by(ArchiveRun.period_key.desc()).limit(1)
            )
        ).scalars().first()
        if active_patterns or impacts or archive_latest:
            archivist_feedback = {
                "patterns": [
                    {
                        "pattern_id": str(p.pattern_id),
                        "ticker": p.ticker,
                        "pattern_type": p.pattern_type,
                        "status": p.status,
                        "confidence_pct": float(p.confidence_pct),
                        "accuracy_pct": float(p.accuracy_pct),
                        "occurrence_count": int(p.occurrence_count or 0),
                        "description": p.description,
                    }
                    for p in active_patterns
                ],
                "impacts": [
                    {
                        "announcement_type": i.announcement_type,
                        "period_key": i.period_key.isoformat(),
                        "sample_count": int(i.sample_count or 0),
                        "avg_change_1d": float(i.avg_change_1d) if i.avg_change_1d is not None else None,
                        "positive_rate": float(i.positive_rate) if i.positive_rate is not None else None,
                        "negative_rate": float(i.negative_rate) if i.negative_rate is not None else None,
                    }
                    for i in impacts
                ],
                "archive_latest_weekly": (
                    {
                        "period_key": archive_latest.period_key.isoformat(),
                        "status": archive_latest.status,
                        "summary": archive_latest.summary or {},
                        "updated_at": archive_latest.updated_at.isoformat() if archive_latest.updated_at else None,
                    }
                    if archive_latest
                    else None
                ),
            }
            calibration_feedback = _extract_calibration_feedback(archivist_feedback)
        else:
            degraded_reasons.append("archivist_feedback_unavailable")

    inputs_summary = {
        "briefing": {
            "available": briefing_row is not None,
            "briefing_date": str(briefing_row.briefing_date) if briefing_row else None,
            "status": briefing_row.status if briefing_row else None,
        },
        "announcements": {
            "available": True,
            "count": len(announcements),
        },
        "sentiment": {
            "available": bool(sentiment_rows),
            "week_start": str(sentiment_week) if sentiment_week else None,
            "status": sentiment_status,
            "rows": len(sentiment_rows),
        },
        "archivist_feedback": {
            "available": bool(archivist_feedback),
            "patterns": len((archivist_feedback or {}).get("patterns") or []),
            "impacts": len((archivist_feedback or {}).get("impacts") or []),
        },
        "market_date": str(market_date) if market_date else None,
        "movers": {
            "available": bool(gainers or losers),
            "gainers_count": len(gainers),
            "losers_count": len(losers),
        },
    }
    global_theme_summary = []
    if briefing_row is not None and isinstance(briefing_row.metrics, dict):
        raw_themes = briefing_row.metrics.get("global_themes")
        if isinstance(raw_themes, list):
            global_theme_summary = [row for row in raw_themes if isinstance(row, dict)]

    return InputsBundle(
        report_type=report_type,
        period_key=period_key,
        market_date=market_date,
        briefing=(
            {
                "briefing_date": str(briefing_row.briefing_date),
                "status": briefing_row.status,
                "subject": briefing_row.subject,
                "metrics": briefing_row.metrics or {},
                "email_sent_at": briefing_row.email_sent_at.isoformat() if briefing_row.email_sent_at else None,
            }
            if briefing_row
            else None
        ),
        announcements=[
            {
                "announcement_id": row.announcement_id,
                "ticker": row.ticker,
                "type": row.announcement_type,
                "headline": row.headline,
                "url": row.url,
                "date": row.announcement_date.isoformat() if row.announcement_date else None,
                "source_id": row.source_id,
                "type_confidence": float(row.type_confidence),
                "severity": (row.raw_payload or {}).get("severity"),
                "alpha_context": (row.raw_payload or {}).get("alpha_context"),
                "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                "scope": (row.raw_payload or {}).get("scope"),
                "theme": (row.raw_payload or {}).get("theme"),
                "signal_class": (row.raw_payload or {}).get("signal_class"),
                "kenya_impact_score": (row.raw_payload or {}).get("kenya_impact_score"),
                "affected_sectors": (row.raw_payload or {}).get("affected_sectors") or [],
                "transmission_channels": (row.raw_payload or {}).get("transmission_channels") or [],
            }
            for row in announcements
        ],
        sentiment_rows=[
            {
                "ticker": row.ticker,
                "company_name": row.company_name,
                "mentions_count": int(row.mentions_count),
                "bullish_pct": float(row.bullish_pct),
                "bearish_pct": float(row.bearish_pct),
                "neutral_pct": float(row.neutral_pct),
                "weighted_score": float(row.weighted_score),
                "confidence": float(row.confidence),
                "wow_delta": float(row.wow_delta) if row.wow_delta is not None else None,
                "notable_quotes": row.notable_quotes or [],
                "top_sources": row.top_sources or {},
            }
            for row in sentiment_rows
        ],
        index_rows=[
            {
                "index_name": row.index_name,
                "value": float(row.value) if row.value is not None else None,
                "change_val": float(row.change_val) if row.change_val is not None else None,
                "pct_change": float(row.pct_change) if row.pct_change is not None else None,
                "source_id": row.source_id,
            }
            for row in index_rows
        ],
        fx_rows=[
            {
                "pair": row.pair,
                "rate": float(row.rate),
                "source_id": row.source_id,
            }
            for row in fx_rows
        ],
        movers=gainers,
        losers=losers,
        price_history=price_history,
        global_theme_summary=global_theme_summary,
        archivist_feedback=archivist_feedback,
        calibration_feedback=calibration_feedback,
        degraded_reasons=sorted(set(degraded_reasons)),
        inputs_summary=inputs_summary,
        upstream_quality={},
    )
