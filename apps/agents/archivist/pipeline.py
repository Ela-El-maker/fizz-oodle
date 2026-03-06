from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from apps.agents.archivist.email import build_archive_subject, send_archive_email
from apps.agents.archivist.render import make_archive_payload_hash, render_archive_html
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.event_schemas import ArchivistPatternsUpdatedV1
from apps.core.events import publish_archivist_patterns_updated
from apps.core.logger import get_logger
from apps.core.models import (
    AccuracyScore,
    AnalystReport,
    Announcement,
    ArchiveRun,
    ImpactStat,
    OutcomeTracking,
    Pattern,
    PatternOccurrence,
    SentimentWeekly,
)
from apps.core.run_service import fail_run, finish_run, start_run
from apps.reporting.composer.renderers import from_archive_summary

logger = get_logger(__name__)
settings = get_settings()


def _week_start_eat(today: date | None = None) -> date:
    if today is None:
        today = datetime.now(ZoneInfo("Africa/Nairobi")).date()
    return today - timedelta(days=today.weekday())


def _month_start(today: date | None = None) -> date:
    if today is None:
        today = datetime.now(ZoneInfo("Africa/Nairobi")).date()
    return today.replace(day=1)


def _safe_pct(n: int, d: int) -> float:
    if d <= 0:
        return 0.0
    return round((n / d) * 100.0, 2)


def _grade_for_accuracy(acc: float, samples: int) -> str:
    if samples < 3:
        return "insufficient"
    if acc >= 75:
        return "excellent"
    if acc >= 60:
        return "good"
    if acc >= 45:
        return "fair"
    return "poor"


def _infer_market_regime(reports: list[dict]) -> str:
    regime_counts: Counter[str] = Counter()
    for report in reports[:50]:
        payload = report.get("json_payload") if isinstance(report, dict) else None
        if not isinstance(payload, dict):
            continue
        signal_intelligence = payload.get("signal_intelligence") if isinstance(payload.get("signal_intelligence"), dict) else {}
        regime = str(signal_intelligence.get("market_regime") or "").strip().lower()
        if regime:
            regime_counts[regime] += 1
    if not regime_counts:
        return "unknown"
    return regime_counts.most_common(1)[0][0]


def _lifecycle_thresholds_for_regime(regime: str) -> dict:
    promotion_threshold = float(settings.ARCHIVIST_PROMOTION_THRESHOLD_PCT)
    retire_threshold = float(settings.ARCHIVIST_RETIRE_THRESHOLD_PCT)
    min_confirm = int(settings.ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM)
    min_retire = int(settings.ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE)

    if bool(settings.ARCHIVIST_REGIME_ADJUSTMENTS_ENABLED):
        normalized = str(regime or "").lower()
        if normalized.startswith("risk_off"):
            promotion_threshold += float(settings.ARCHIVIST_REGIME_RISK_OFF_PROMOTION_DELTA_PCT)
            retire_threshold += float(settings.ARCHIVIST_REGIME_RISK_OFF_RETIRE_DELTA_PCT)
            min_confirm = max(min_confirm, int(settings.ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM) + 1)
        elif normalized.startswith("risk_on"):
            promotion_threshold += float(settings.ARCHIVIST_REGIME_RISK_ON_PROMOTION_DELTA_PCT)
            retire_threshold += float(settings.ARCHIVIST_REGIME_RISK_ON_RETIRE_DELTA_PCT)

    return {
        "market_regime": regime or "unknown",
        "promotion_threshold_pct": round(max(0.0, min(100.0, promotion_threshold)), 2),
        "retire_threshold_pct": round(max(0.0, min(100.0, retire_threshold)), 2),
        "min_occurrences_for_confirm": max(1, int(min_confirm)),
        "min_occurrences_for_retire": max(1, int(min_retire)),
    }


def _replacement_pressure_from_inventory(inventory: dict) -> dict:
    active_confirmed = int(inventory.get("active_confirmed") or 0)
    retired_recent = int(inventory.get("retired_recent_window") or 0)
    dominance_ratio = retired_recent / max(1, active_confirmed)
    replacement_pressure_high = (
        retired_recent >= int(settings.ARCHIVIST_REPLACEMENT_MIN_ACTIVE_CONFIRMED)
        and dominance_ratio >= float(settings.ARCHIVIST_REPLACEMENT_RETIRE_DOMINANCE_RATIO)
    ) or (active_confirmed < int(settings.ARCHIVIST_REPLACEMENT_MIN_ACTIVE_CONFIRMED))
    return {
        "active_confirmed": active_confirmed,
        "retired_recent_window": retired_recent,
        "retired_dominance_ratio": round(dominance_ratio, 3),
        "replacement_pressure_high": bool(replacement_pressure_high),
        "window_days": int(settings.ARCHIVIST_REPLACEMENT_RETIRE_DOMINANCE_DAYS),
        "min_active_confirmed_target": int(settings.ARCHIVIST_REPLACEMENT_MIN_ACTIVE_CONFIRMED),
    }


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except Exception:
        return None


async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict:
    resp = await client.get(url, params=params, headers={"X-API-Key": settings.API_KEY})
    resp.raise_for_status()
    return resp.json()


async def _fetch_json_or_empty(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None,
    warning_key: str,
    metrics: dict,
) -> dict:
    try:
        payload = await _fetch_json(client, url, params=params)
    except Exception as exc:  # noqa: PERF203
        logger.warning("archivist_upstream_fetch_failed", url=url, warning_key=warning_key, error=str(exc))
        warnings = metrics.setdefault("warnings", [])
        if warning_key not in warnings:
            warnings.append(warning_key)
        metrics["degraded"] = True
        return {}
    return payload if isinstance(payload, dict) else {}


async def _fetch_paginated_items_or_empty(
    client: httpx.AsyncClient,
    url: str,
    *,
    base_params: dict | None,
    warning_key: str,
    metrics: dict,
    page_limit: int = 200,
    max_pages: int = 10,
) -> list[dict]:
    items: list[dict] = []
    params_base = dict(base_params or {})
    params_base.pop("limit", None)
    params_base.pop("offset", None)
    total: int | None = None

    for page in range(max_pages):
        offset = page * page_limit
        payload = await _fetch_json_or_empty(
            client,
            url,
            params={**params_base, "limit": page_limit, "offset": offset},
            warning_key=warning_key,
            metrics=metrics,
        )
        page_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(page_items, list):
            break
        items.extend([row for row in page_items if isinstance(row, dict)])

        if total is None:
            raw_total = payload.get("total") if isinstance(payload, dict) else None
            if isinstance(raw_total, int) and raw_total >= 0:
                total = raw_total

        if len(page_items) < page_limit:
            break
        if total is not None and len(items) >= total:
            break

    return items


async def _compute_announcement_impact(client: httpx.AsyncClient, ticker: str, announcement_date: date) -> float | None:
    to_date = announcement_date + timedelta(days=7)
    payload = await _fetch_json(
        client,
        f"{settings.AGENT_A_SERVICE_URL}/prices/{ticker}",
        params={"from": announcement_date.isoformat(), "to": to_date.isoformat()},
    )
    rows = payload.get("items") or []
    if len(rows) < 2:
        return None
    rows_sorted = sorted(rows, key=lambda x: x.get("date") or "")
    first = rows_sorted[0].get("close")
    second = rows_sorted[1].get("close")
    if first in (None, 0) or second is None:
        return None
    return ((float(second) - float(first)) / float(first)) * 100.0


async def _pattern_inventory(session) -> dict:
    rows = (await session.execute(select(Pattern))).scalars().all()
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(days=int(settings.ARCHIVIST_REPLACEMENT_RETIRE_DOMINANCE_DAYS))

    active_confirmed = sum(1 for row in rows if bool(row.active) and str(row.status).lower() == "confirmed")
    retired_recent = sum(
        1
        for row in rows
        if str(row.status).lower() == "retired" and (row.updated_at is not None and row.updated_at >= window_start)
    )
    candidate_count = sum(1 for row in rows if str(row.status).lower() == "candidate")

    return {
        "total": len(rows),
        "active_confirmed": active_confirmed,
        "candidate": candidate_count,
        "retired_recent_window": retired_recent,
    }


async def _upsert_pattern(
    *,
    session,
    ticker: str,
    pattern_type: str,
    description: str,
    confidence_pct: float,
    accuracy_pct: float,
    avg_impact_1d: float | None = None,
    lifecycle_thresholds: dict | None = None,
):
    thresholds = lifecycle_thresholds or _lifecycle_thresholds_for_regime("unknown")
    min_confirm = int(thresholds.get("min_occurrences_for_confirm") or settings.ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM)
    min_retire = int(thresholds.get("min_occurrences_for_retire") or settings.ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE)
    promotion_threshold = float(thresholds.get("promotion_threshold_pct") or settings.ARCHIVIST_PROMOTION_THRESHOLD_PCT)
    retire_threshold = float(thresholds.get("retire_threshold_pct") or settings.ARCHIVIST_RETIRE_THRESHOLD_PCT)

    row = (
        await session.execute(select(Pattern).where(and_(Pattern.ticker == ticker, Pattern.pattern_type == pattern_type)))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        row = Pattern(
            ticker=ticker,
            pattern_type=pattern_type,
            description=description,
            status="candidate",
            confidence_pct=confidence_pct,
            accuracy_pct=accuracy_pct,
            occurrence_count=1,
            avg_impact_1d=avg_impact_1d,
            metadata_json={},
            active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
    else:
        row.description = description
        row.confidence_pct = confidence_pct
        row.accuracy_pct = accuracy_pct
        row.occurrence_count = int(row.occurrence_count or 0) + 1
        row.avg_impact_1d = avg_impact_1d if avg_impact_1d is not None else row.avg_impact_1d
        row.updated_at = now
        if (
            row.occurrence_count >= min_confirm
            and row.accuracy_pct >= promotion_threshold
        ):
            row.status = "confirmed"
            row.active = True
        if (
            row.occurrence_count >= min_retire
            and row.accuracy_pct < retire_threshold
        ):
            row.status = "retired"
            row.active = False

    observed_on = datetime.now(ZoneInfo("Africa/Nairobi")).date()
    occ = (
        await session.execute(
            select(PatternOccurrence).where(and_(PatternOccurrence.pattern_id == row.pattern_id, PatternOccurrence.observed_on == observed_on))
        )
    ).scalar_one_or_none()
    if occ is None:
        session.add(
            PatternOccurrence(
                pattern_id=row.pattern_id,
                ticker=ticker,
                observed_on=observed_on,
                strength=int(round(confidence_pct)),
                source_refs={},
            )
        )


async def _apply_pattern_lifecycle(session, lifecycle_thresholds: dict | None = None) -> int:
    thresholds = lifecycle_thresholds or _lifecycle_thresholds_for_regime("unknown")
    min_confirm = int(thresholds.get("min_occurrences_for_confirm") or settings.ARCHIVIST_MIN_OCCURRENCES_FOR_CONFIRM)
    min_retire = int(thresholds.get("min_occurrences_for_retire") or settings.ARCHIVIST_MIN_OCCURRENCES_FOR_RETIRE)
    promotion_threshold = float(thresholds.get("promotion_threshold_pct") or settings.ARCHIVIST_PROMOTION_THRESHOLD_PCT)
    retire_threshold = float(thresholds.get("retire_threshold_pct") or settings.ARCHIVIST_RETIRE_THRESHOLD_PCT)

    rows = (await session.execute(select(Pattern))).scalars().all()
    changed = 0
    for row in rows:
        before = (row.status, row.active)
        if (
            row.occurrence_count >= min_confirm
            and float(row.accuracy_pct) >= promotion_threshold
        ):
            row.status = "confirmed"
            row.active = True
        if (
            row.occurrence_count >= min_retire
            and float(row.accuracy_pct) < retire_threshold
        ):
            row.status = "retired"
            row.active = False
        after = (row.status, row.active)
        if after != before:
            row.updated_at = datetime.now(timezone.utc)
            changed += 1
    return changed


async def _upsert_pattern_compat(*, lifecycle_thresholds: dict | None, **kwargs) -> None:
    try:
        await _upsert_pattern(lifecycle_thresholds=lifecycle_thresholds, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument 'lifecycle_thresholds'" not in str(exc):
            raise
        await _upsert_pattern(**kwargs)


async def _apply_pattern_lifecycle_compat(session, lifecycle_thresholds: dict | None) -> int:
    try:
        return await _apply_pattern_lifecycle(session, lifecycle_thresholds=lifecycle_thresholds)
    except TypeError as exc:
        if "unexpected keyword argument 'lifecycle_thresholds'" not in str(exc):
            raise
        return await _apply_pattern_lifecycle(session)


def _filter_sentiment_rows(sentiment_rows: list[dict], selected_type: str, target_period: date) -> list[dict]:
    parsed: list[tuple[date, dict]] = []
    for row in sentiment_rows:
        wk = _parse_iso_date(row.get("week_start"))
        if wk is None:
            continue
        parsed.append((wk, row))
    if not parsed:
        return []

    if selected_type == "weekly":
        current = [row for wk, row in parsed if wk == target_period]
        if current:
            return current
        latest_week = max(wk for wk, _ in parsed if wk <= target_period)
        return [row for wk, row in parsed if wk == latest_week]

    window_start = target_period - timedelta(weeks=int(settings.ARCHIVIST_MONTHLY_LOOKBACK_WEEKS))
    return [row for wk, row in parsed if window_start <= wk <= target_period]


def _monthly_sentiment_trends(rows: list[dict]) -> list[dict]:
    by_ticker: dict[str, list[tuple[date, float, float]]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        wk = _parse_iso_date(row.get("week_start"))
        if not ticker or wk is None:
            continue
        score = float(row.get("weighted_score") or 0.0)
        conf = float(row.get("confidence") or 0.0)
        by_ticker.setdefault(ticker, []).append((wk, score, conf))

    trends: list[dict] = []
    for ticker, points in by_ticker.items():
        points_sorted = sorted(points, key=lambda p: p[0])
        if len(points_sorted) < 2:
            continue
        delta = points_sorted[-1][1] - points_sorted[0][1]
        avg_conf = sum(p[2] for p in points_sorted) / len(points_sorted)
        trends.append(
            {
                "ticker": ticker,
                "weeks": len(points_sorted),
                "delta": round(delta, 4),
                "avg_confidence": round(avg_conf, 4),
                "latest_score": round(points_sorted[-1][1], 4),
            }
        )
    return sorted(trends, key=lambda x: abs(x["delta"]), reverse=True)


def _derive_from_analyst_reports(reports: list[dict]) -> tuple[list[dict], list[dict]]:
    sentiment_rows: list[dict] = []
    announcements: list[dict] = []
    seen_sentiment: set[tuple[str, str]] = set()
    seen_ann: set[tuple[str, str, str]] = set()

    for report in reports:
        payload = report.get("json_payload") if isinstance(report, dict) else None
        if not isinstance(payload, dict):
            continue
        week_start = str(report.get("period_key") or "")

        for row in payload.get("sentiment_pulse") or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").upper().strip()
            if not ticker:
                continue
            key = (week_start, ticker)
            if key in seen_sentiment:
                continue
            seen_sentiment.add(key)
            sentiment_rows.append(
                {
                    "week_start": week_start,
                    "ticker": ticker,
                    "mentions_count": int(row.get("mentions") or 0),
                    "weighted_score": float(row.get("score") or 0.0),
                    "confidence": float(row.get("confidence_pct") or 0.0) / 100.0,
                    "wow_delta": None,
                }
            )

        for evt in payload.get("key_events") or []:
            if not isinstance(evt, dict):
                continue
            ticker = str(evt.get("ticker") or "").upper().strip()
            ann_type = str(evt.get("type") or "").strip().lower()
            ann_date = str(evt.get("date") or report.get("period_key") or "")
            if not ticker or not ann_type or not ann_date:
                continue
            key = (ticker, ann_type, ann_date)
            if key in seen_ann:
                continue
            seen_ann.add(key)
            announcements.append(
                {
                    "ticker": ticker,
                    "announcement_type": ann_type,
                    "announcement_date": ann_date,
                    "scope": evt.get("scope"),
                    "theme": evt.get("theme"),
                    "kenya_impact_score": evt.get("kenya_impact_score"),
                }
            )

    return sentiment_rows, announcements


def _build_global_pattern_context(
    *,
    theme_rows: list[dict],
    announcements: list[dict],
) -> dict:
    top_themes = sorted(
        [
            {
                "theme": str(row.get("theme") or "").strip().lower(),
                "mentions": int(row.get("mentions") or row.get("count") or 0),
                "weighted_score": float(row.get("weighted_score") or 0.0),
                "kenya_relevance_avg": float(row.get("kenya_relevance_avg") or 0.0),
            }
            for row in theme_rows
            if isinstance(row, dict) and str(row.get("theme") or "").strip()
        ],
        key=lambda row: (float(row.get("kenya_relevance_avg") or 0.0), int(row.get("mentions") or 0)),
        reverse=True,
    )[:5]

    high_impact_announcements = [
        row
        for row in announcements
        if str(row.get("scope") or "").strip().lower() == "global_outside"
        and int(row.get("kenya_impact_score") or 0) >= int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD)
    ]
    global_announcement_bursts: dict[str, int] = {}
    for row in high_impact_announcements:
        theme = str(row.get("theme") or "global_macro").strip().lower()
        global_announcement_bursts[theme] = int(global_announcement_bursts.get(theme) or 0) + 1

    pattern_candidates: list[dict] = []
    for row in top_themes:
        theme = str(row.get("theme") or "").strip().lower()
        mentions = int(row.get("mentions") or 0)
        weighted_score = float(row.get("weighted_score") or 0.0)
        kenya_relevance = float(row.get("kenya_relevance_avg") or 0.0)
        burst = int(global_announcement_bursts.get(theme) or 0)
        if mentions >= 3 and abs(weighted_score) >= 0.12 and kenya_relevance >= 0.45:
            pattern_candidates.append(
                {
                    "pattern_type": "theme_price_divergence",
                    "theme": theme,
                    "mentions": mentions,
                    "weighted_score": round(weighted_score, 4),
                    "kenya_relevance_avg": round(kenya_relevance, 3),
                    "announcement_burst": burst,
                    "confidence_pct": round(min(95.0, 40.0 + (mentions * 4.0) + (abs(weighted_score) * 60.0)), 2),
                }
            )
        if theme in {"oil", "usd_strength", "bonds_yields", "global_equities_trading", "global_risk"} and burst >= 2:
            pattern_candidates.append(
                {
                    "pattern_type": "macro_shock_sensitivity",
                    "theme": theme,
                    "mentions": mentions,
                    "weighted_score": round(weighted_score, 4),
                    "kenya_relevance_avg": round(kenya_relevance, 3),
                    "announcement_burst": burst,
                    "confidence_pct": round(min(95.0, 55.0 + (burst * 8.0) + (abs(weighted_score) * 45.0)), 2),
                }
            )
    pattern_candidates.sort(
        key=lambda row: (
            float(row.get("confidence_pct") or 0.0),
            int(row.get("announcement_burst") or 0),
            int(row.get("mentions") or 0),
        ),
        reverse=True,
    )

    return {
        "top_themes": top_themes,
        "high_impact_global_announcements": len(high_impact_announcements),
        "global_announcement_bursts": global_announcement_bursts,
        "global_pattern_candidates": pattern_candidates[:10],
    }


def _compute_upstream_quality(
    *,
    reports: list[dict],
    sentiment_rows: list[dict],
    announcements: list[dict],
    warnings: list[str],
    input_mode: str,
) -> dict:
    analyst_only = input_mode == "analyst_only"
    if analyst_only:
        availability_checks = {"analyst_reports": bool(reports)}
        availability_pct = round((sum(1 for ok in availability_checks.values() if ok) / len(availability_checks)) * 100.0, 2)
        coverage_checks = {
            "has_reports": len(reports) > 0,
            "has_sentiment_from_reports": len(sentiment_rows) > 0,
            "has_announcements_from_reports": len(announcements) > 0,
        }
        coverage_pct = round((sum(1 for ok in coverage_checks.values() if ok) / len(coverage_checks)) * 100.0, 2)
        degradation_count = len(set(warnings))
        score = round(max(0.0, min(100.0, (availability_pct * 0.8) + (coverage_pct * 0.2) - (degradation_count * 4.0))), 2)
        return {
            "availability_checks": availability_checks,
            "availability_pct": availability_pct,
            "coverage_checks": coverage_checks,
            "coverage_pct": coverage_pct,
            "degradation_count": degradation_count,
            "score": score,
            "input_mode": input_mode,
        }

    availability_checks = {
        "analyst_reports": bool(reports),
        "sentiment_rows": bool(sentiment_rows),
        "announcements": bool(announcements),
    }
    availability_pct = round((sum(1 for ok in availability_checks.values() if ok) / len(availability_checks)) * 100.0, 2)
    coverage_checks = {
        "has_reports": len(reports) > 0,
        "has_sentiment_rows": len(sentiment_rows) > 0,
        "has_announcements": len(announcements) > 0,
    }
    coverage_pct = round((sum(1 for ok in coverage_checks.values() if ok) / len(coverage_checks)) * 100.0, 2)
    degradation_count = len(set(warnings))
    score = round(max(0.0, min(100.0, (availability_pct * 0.7) + (coverage_pct * 0.3) - (degradation_count * 4.0))), 2)
    return {
        "availability_checks": availability_checks,
        "availability_pct": availability_pct,
        "coverage_checks": coverage_checks,
        "coverage_pct": coverage_pct,
        "degradation_count": degradation_count,
        "score": score,
        "input_mode": input_mode,
    }


def _build_archive_human_summary(
    *,
    selected_type: str,
    target_period: date,
    metrics: dict,
    upstream_quality: dict,
    pattern_rows: list[Pattern],
    impact_rows: list[ImpactStat],
) -> dict:
    run_mode = "degraded" if bool(metrics.get("degraded")) else "healthy"
    quality_score = float(upstream_quality.get("score") or 0.0)
    patterns_upserted = int(metrics.get("patterns_upserted") or 0)
    impacts_upserted = int(metrics.get("impacts_upserted") or 0)
    reports_considered = int(metrics.get("reports_considered") or 0)
    warnings = [str(w).strip() for w in (metrics.get("warnings") or []) if str(w).strip()]
    replacement = metrics.get("replacement_pressure") or {}
    lifecycle_thresholds = metrics.get("lifecycle_thresholds") or {}

    headline = (
        f"Archivist {selected_type} archive for {target_period.isoformat()} is {run_mode} "
        f"(upstream quality {quality_score:.2f}/100)."
    )
    plain_summary = (
        f"Processed {reports_considered} analyst reports, upserted {patterns_upserted} patterns "
        f"and {impacts_upserted} impact rows."
    )

    top_patterns = sorted(
        pattern_rows,
        key=lambda p: (float(p.accuracy_pct or 0.0), int(p.occurrence_count or 0)),
        reverse=True,
    )[:3]
    top_impacts = sorted(
        impact_rows,
        key=lambda i: abs(float(i.avg_change_1d or 0.0)),
        reverse=True,
    )[:3]

    bullets: list[str] = [
        f"Archive mode: {run_mode}.",
        f"Quality score: {quality_score:.2f}/100.",
        f"Patterns upserted: {patterns_upserted}. Impacts upserted: {impacts_upserted}.",
    ]
    if top_patterns:
        bullets.append(
            "Top patterns: "
            + "; ".join(
                f"{p.ticker} {p.pattern_type} ({float(p.accuracy_pct or 0.0):.1f}% acc, {int(p.occurrence_count or 0)} obs)"
                for p in top_patterns
            )
        )
    if top_impacts:
        bullets.append(
            "Top impact classes: "
            + "; ".join(
                f"{i.announcement_type} ({float(i.avg_change_1d or 0.0):+.2f}% 1d, n={int(i.sample_count or 0)})"
                for i in top_impacts
            )
        )
    if warnings:
        bullets.append("Warnings: " + ", ".join(warnings[:5]))
    if replacement:
        bullets.append(
            "Pattern inventory: "
            f"{int(replacement.get('active_confirmed') or 0)} active-confirmed, "
            f"{int(replacement.get('retired_recent_window') or 0)} retired in last "
            f"{int(replacement.get('window_days') or 0)}d."
        )
        if bool(replacement.get("replacement_pressure_high")):
            bullets.append(
                "Replacement pressure is high; prioritizing new candidate pattern discovery this cycle."
            )
    if lifecycle_thresholds:
        bullets.append(
            "Lifecycle thresholds: "
            f"promote >= {float(lifecycle_thresholds.get('promotion_threshold_pct') or 0.0):.1f}% "
            f"(min {int(lifecycle_thresholds.get('min_occurrences_for_confirm') or 0)}), "
            f"retire < {float(lifecycle_thresholds.get('retire_threshold_pct') or 0.0):.1f}% "
            f"(min {int(lifecycle_thresholds.get('min_occurrences_for_retire') or 0)})."
        )

    return {
        "headline": headline,
        "plain_summary": plain_summary,
        "bullets": bullets,
        "coverage": {
            "reports_considered": reports_considered,
            "patterns_upserted": patterns_upserted,
            "impacts_upserted": impacts_upserted,
            "upstream_quality_score": quality_score,
        },
        "flags": {
            "degraded": bool(metrics.get("degraded")),
            "email_sent": bool(metrics.get("email_sent")),
            "email_skipped": bool(metrics.get("email_skipped")),
        },
    }


async def run_archivist_pipeline(
    *,
    run_id: str | None = None,
    run_type: str | None = None,
    period_key: date | None = None,
    force_send: bool | None = None,  # reserved for compatibility
    email_recipients_override: str | None = None,
) -> dict:
    rid = await start_run("archivist", run_id=run_id)
    selected_type = (run_type or "weekly").strip().lower()
    if selected_type not in {"weekly", "monthly"}:
        raise ValueError(f"Unsupported run_type={selected_type}")

    target_period = period_key or (_week_start_eat() if selected_type == "weekly" else _month_start())

    metrics: dict = {
        "run_type": selected_type,
        "period_key": target_period.isoformat(),
        "input_mode": str(settings.ARCHIVIST_INPUT_MODE or "analyst_only").strip().lower(),
        "reports_considered": 0,
        "patterns_upserted": 0,
        "impacts_upserted": 0,
        "outcomes_upserted": 0,
        "accuracy_rows_upserted": 0,
        "lifecycle_updates": 0,
        "email_sent": False,
        "email_skipped": False,
        "email_error": None,
        "degraded": False,
        "warnings": [],
        "market_regime": "unknown",
        "lifecycle_thresholds": {},
        "replacement_pressure": {},
        "allow_pattern_promotion": False,
        "allow_pattern_promotion_reason": "upstream_quality_gate",
    }
    processed = 0
    created = 0
    errors = 0

    try:
        ann_to = datetime.now(timezone.utc)
        lookback_days = (
            int(settings.ARCHIVIST_WEEKLY_LOOKBACK_DAYS)
            if selected_type == "weekly"
            else int(settings.ARCHIVIST_MONTHLY_LOOKBACK_WEEKS) * 7
        )
        ann_from = ann_to - timedelta(days=lookback_days)

        reports: list[dict] = []
        sentiment_rows_raw: list[dict] = []
        announcements: list[dict] = []
        theme_rows: list[dict] = []
        input_mode = str(settings.ARCHIVIST_INPUT_MODE or "analyst_only").strip().lower()
        if input_mode not in {"analyst_only", "hybrid"}:
            input_mode = "analyst_only"
        metrics["input_mode"] = input_mode

        # DB-first read path.
        try:
            async with get_session() as preload_session:
                report_rows = (
                    await preload_session.execute(
                        select(AnalystReport).order_by(AnalystReport.generated_at.desc()).limit(500)
                    )
                ).scalars().all()
                reports = [
                    {
                        "report_id": str(row.report_id),
                        "report_type": row.report_type,
                        "period_key": row.period_key.isoformat(),
                        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                        "degraded": bool(row.degraded),
                        "json_payload": row.json_payload or {},
                        "metrics": row.metrics or {},
                    }
                    for row in report_rows
                ]

                if input_mode != "analyst_only":
                    sentiment_rows_db = (
                        await preload_session.execute(
                            select(SentimentWeekly)
                            .where(SentimentWeekly.week_start >= (target_period - timedelta(weeks=int(settings.ARCHIVIST_MONTHLY_LOOKBACK_WEEKS))))
                            .order_by(SentimentWeekly.week_start.desc(), SentimentWeekly.ticker.asc())
                            .limit(2000)
                        )
                    ).scalars().all()
                    sentiment_rows_raw = [
                        {
                            "week_start": row.week_start.isoformat(),
                            "ticker": row.ticker,
                            "mentions_count": int(row.mentions_count),
                            "weighted_score": float(row.weighted_score),
                            "confidence": float(row.confidence),
                            "wow_delta": float(row.wow_delta) if row.wow_delta is not None else None,
                        }
                        for row in sentiment_rows_db
                    ]

                    ann_rows = (
                        await preload_session.execute(
                            select(Announcement)
                            .where(and_(Announcement.first_seen_at >= ann_from, Announcement.first_seen_at <= ann_to))
                            .order_by(Announcement.first_seen_at.desc())
                            .limit(2000)
                        )
                    ).scalars().all()
                    announcements = [
                        {
                            "announcement_id": row.announcement_id,
                            "ticker": row.ticker,
                            "announcement_type": row.announcement_type,
                            "announcement_date": row.announcement_date.isoformat() if row.announcement_date else None,
                            "scope": (row.raw_payload or {}).get("scope"),
                            "theme": (row.raw_payload or {}).get("theme"),
                            "kenya_impact_score": (row.raw_payload or {}).get("kenya_impact_score"),
                        }
                        for row in ann_rows
                    ]
        except SQLAlchemyError as exc:
            logger.warning("archivist_db_preload_unavailable", error=str(exc))
            if "db_snapshot_unavailable" not in metrics["warnings"]:
                metrics["warnings"].append("db_snapshot_unavailable")
            metrics["degraded"] = True

        if settings.ARCHIVIST_USE_API_FALLBACK:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if not reports:
                    reports = await _fetch_paginated_items_or_empty(
                        client,
                        f"{settings.AGENT_D_SERVICE_URL}/reports",
                        base_params={},
                        warning_key="no_analyst_reports",
                        metrics=metrics,
                    )
                if input_mode != "analyst_only":
                    if not sentiment_rows_raw:
                        sentiment_rows_raw = await _fetch_paginated_items_or_empty(
                            client,
                            f"{settings.AGENT_C_SERVICE_URL}/sentiment/weekly",
                            base_params={},
                            warning_key="no_sentiment_rows",
                            metrics=metrics,
                        )
                    if not announcements:
                        announcements = await _fetch_paginated_items_or_empty(
                            client,
                            f"{settings.AGENT_B_SERVICE_URL}/announcements",
                            base_params={"from": ann_from.isoformat(), "to": ann_to.isoformat()},
                            warning_key="no_announcements",
                            metrics=metrics,
                        )
                    try:
                        theme_payload = await _fetch_json(
                            client,
                            f"{settings.AGENT_C_SERVICE_URL}/sentiment/themes/weekly",
                            params={"week_start": target_period.isoformat()} if selected_type == "weekly" else None,
                        )
                    except Exception:
                        theme_payload = {}
                    if isinstance(theme_payload, dict) and isinstance(theme_payload.get("items"), list):
                        theme_rows = [row for row in theme_payload.get("items") or [] if isinstance(row, dict)]

                if input_mode == "analyst_only":
                    sentiment_rows_raw, announcements = _derive_from_analyst_reports(reports)

                metrics["reports_considered"] = len(reports)
                if not reports and "no_analyst_reports" not in metrics["warnings"]:
                    metrics["warnings"].append("no_analyst_reports")
                    metrics["degraded"] = True

                sentiment_rows = _filter_sentiment_rows(sentiment_rows_raw, selected_type=selected_type, target_period=target_period)
                if input_mode != "analyst_only":
                    if not sentiment_rows and "no_sentiment_rows" not in metrics["warnings"]:
                        metrics["warnings"].append("no_sentiment_rows")

                    if not announcements and "no_announcements" not in metrics["warnings"]:
                        metrics["warnings"].append("no_announcements")
        metrics["reports_considered"] = len(reports)
        if input_mode == "analyst_only":
            sentiment_rows_raw, announcements = _derive_from_analyst_reports(reports)
        sentiment_rows = _filter_sentiment_rows(sentiment_rows_raw, selected_type=selected_type, target_period=target_period)
        if not reports and "no_analyst_reports" not in metrics["warnings"]:
            metrics["warnings"].append("no_analyst_reports")
        if input_mode != "analyst_only":
            if not sentiment_rows and "no_sentiment_rows" not in metrics["warnings"]:
                metrics["warnings"].append("no_sentiment_rows")
            if not announcements and "no_announcements" not in metrics["warnings"]:
                metrics["warnings"].append("no_announcements")
        # If API fallback restored complete upstream inputs, clear DB snapshot warning.
        if input_mode == "analyst_only":
            if reports and "db_snapshot_unavailable" in metrics["warnings"]:
                metrics["warnings"].remove("db_snapshot_unavailable")
        elif reports and sentiment_rows and announcements and "db_snapshot_unavailable" in metrics["warnings"]:
            metrics["warnings"].remove("db_snapshot_unavailable")
        metrics["degraded"] = bool(metrics["warnings"])
        upstream_quality = _compute_upstream_quality(
            reports=reports,
            sentiment_rows=sentiment_rows,
            announcements=announcements,
            warnings=metrics["warnings"],
            input_mode=input_mode,
        )
        market_regime = _infer_market_regime(reports)
        lifecycle_thresholds = _lifecycle_thresholds_for_regime(market_regime)
        metrics["market_regime"] = market_regime
        metrics["lifecycle_thresholds"] = lifecycle_thresholds
        metrics["upstream_quality"] = upstream_quality
        metrics["global_pattern_context"] = _build_global_pattern_context(
            theme_rows=theme_rows,
            announcements=announcements,
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            async with get_session() as session:
                pre_inventory = await _pattern_inventory(session)
                replacement_pressure = _replacement_pressure_from_inventory(pre_inventory)
                metrics["replacement_pressure"] = replacement_pressure

                upstream_score = float(upstream_quality.get("score") or 0.0)
                allow_pattern_promotion = upstream_score >= float(settings.ARCHIVIST_UPSTREAM_QUALITY_MIN_SCORE)
                allow_reason = "upstream_quality_gate"
                if (
                    not allow_pattern_promotion
                    and bool(replacement_pressure.get("replacement_pressure_high"))
                    and upstream_score >= float(settings.ARCHIVIST_REPLACEMENT_UPSTREAM_QUALITY_FLOOR)
                ):
                    allow_pattern_promotion = True
                    allow_reason = "replacement_pressure_rebuild_mode"
                if not allow_pattern_promotion:
                    if "upstream_quality_low" not in metrics["warnings"]:
                        metrics["warnings"].append("upstream_quality_low")
                    metrics["degraded"] = True
                metrics["allow_pattern_promotion"] = bool(allow_pattern_promotion)
                metrics["allow_pattern_promotion_reason"] = allow_reason

                # Analyst outcomes + accuracy.
                correct = 0
                total = 0
                for report in reports:
                    total += 1
                    is_correct = not bool(report.get("degraded"))
                    correct += 1 if is_correct else 0
                    signal_ref = f"analyst:{report.get('report_id')}"
                    ticker = "MARKET"
                    details = {
                        "report_type": report.get("report_type"),
                        "period_key": report.get("period_key"),
                        "degraded": bool(report.get("degraded")),
                    }
                    now = datetime.now(timezone.utc)
                    stmt = (
                        pg_insert(OutcomeTracking)
                        .values(
                            signal_ref=signal_ref,
                            source_agent="analyst",
                            ticker=ticker,
                            predicted_direction="neutral",
                            actual_direction="flat" if is_correct else "unknown",
                            change_1d=0.0 if is_correct else None,
                            change_5d=0.0 if is_correct else None,
                            grade="correct" if is_correct else "uncertain",
                            details=details,
                            resolved_at=now,
                        )
                        .on_conflict_do_update(
                            index_elements=["signal_ref", "ticker"],
                            set_={
                                "actual_direction": "flat" if is_correct else "unknown",
                                "grade": "correct" if is_correct else "uncertain",
                                "details": details,
                                "resolved_at": now,
                            },
                        )
                    )
                    await session.execute(stmt)
                    metrics["outcomes_upserted"] += 1

                acc_pct = _safe_pct(correct, total)
                acc_grade = _grade_for_accuracy(acc_pct, total)
                acc_row = (
                    await session.execute(
                        select(AccuracyScore).where(
                            and_(
                                AccuracyScore.agent_name == "analyst",
                                AccuracyScore.period_key == target_period,
                                AccuracyScore.ticker == "MARKET",
                            )
                        )
                    )
                ).scalar_one_or_none()
                if acc_row is None:
                    session.add(
                        AccuracyScore(
                            agent_name="analyst",
                            period_key=target_period,
                            ticker="MARKET",
                            sample_count=total,
                            accuracy_pct=acc_pct,
                            grade=acc_grade,
                            details={"correct": correct, "total": total},
                        )
                    )
                    metrics["accuracy_rows_upserted"] += 1
                else:
                    acc_row.sample_count = total
                    acc_row.accuracy_pct = acc_pct
                    acc_row.grade = acc_grade
                    acc_row.details = {"correct": correct, "total": total}
                    acc_row.computed_at = datetime.now(timezone.utc)

                # Sentiment patterns.
                for row in sentiment_rows:
                    if not allow_pattern_promotion:
                        continue
                    mentions = int(row.get("mentions_count") or 0)
                    if mentions < 3:
                        continue
                    wow = row.get("wow_delta")
                    if wow is None:
                        continue
                    wow = float(wow)
                    if abs(wow) < 0.10:
                        continue
                    ticker = str(row.get("ticker") or "").upper()
                    if not ticker:
                        continue
                    trend = "improving" if wow > 0 else "weakening"
                    await _upsert_pattern_compat(
                        session=session,
                        ticker=ticker,
                        pattern_type="sentiment_shift",
                        description=f"{ticker} sentiment is {trend} week-over-week (delta {wow:+.3f}).",
                        confidence_pct=round(float(row.get("confidence") or 0.0) * 100.0, 2),
                        accuracy_pct=acc_pct,
                        avg_impact_1d=wow,
                        lifecycle_thresholds=lifecycle_thresholds,
                    )
                    metrics["patterns_upserted"] += 1
                    processed += 1

                if selected_type == "monthly":
                    for trend in _monthly_sentiment_trends(sentiment_rows):
                        if not allow_pattern_promotion:
                            continue
                        if abs(float(trend["delta"])) < 0.08:
                            continue
                        direction = "improving" if float(trend["delta"]) > 0 else "weakening"
                        await _upsert_pattern_compat(
                            session=session,
                            ticker=trend["ticker"],
                            pattern_type="sentiment_trend_monthly",
                            description=(
                                f"{trend['ticker']} monthly sentiment trend is {direction} "
                                f"({trend['weeks']} weeks, delta {float(trend['delta']):+.3f})."
                            ),
                            confidence_pct=round(float(trend["avg_confidence"]) * 100.0, 2),
                            accuracy_pct=acc_pct,
                            avg_impact_1d=float(trend["delta"]),
                            lifecycle_thresholds=lifecycle_thresholds,
                        )
                        metrics["patterns_upserted"] += 1
                        processed += 1

                # Announcement impact stats.
                grouped: dict[str, list[float]] = {}
                for ann in announcements:
                    ticker = (ann.get("ticker") or "").upper()
                    ann_type = ann.get("announcement_type") or "other"
                    ann_date_raw = ann.get("announcement_date")
                    if not ticker or not ann_date_raw:
                        continue
                    try:
                        ann_date = datetime.fromisoformat(ann_date_raw).date()
                    except Exception:
                        continue
                    try:
                        change_1d = await _compute_announcement_impact(client, ticker, ann_date)
                    except Exception:
                        change_1d = None
                    if change_1d is None:
                        continue
                    grouped.setdefault(ann_type, []).append(change_1d)

                for ann_type, deltas in grouped.items():
                    if not deltas:
                        continue
                    avg = round(sum(deltas) / len(deltas), 4)
                    pos = len([d for d in deltas if d > 0])
                    neg = len([d for d in deltas if d < 0])
                    row = (
                        await session.execute(
                            select(ImpactStat).where(
                                and_(ImpactStat.announcement_type == ann_type, ImpactStat.period_key == target_period)
                            )
                        )
                    ).scalar_one_or_none()
                    details = {"samples": len(deltas), "min": min(deltas), "max": max(deltas)}
                    if row is None:
                        session.add(
                            ImpactStat(
                                announcement_type=ann_type,
                                period_key=target_period,
                                sample_count=len(deltas),
                                avg_change_1d=avg,
                                avg_change_5d=None,
                                avg_change_30d=None,
                                positive_rate=_safe_pct(pos, len(deltas)),
                                negative_rate=_safe_pct(neg, len(deltas)),
                                details=details,
                            )
                        )
                        metrics["impacts_upserted"] += 1
                    else:
                        row.sample_count = len(deltas)
                        row.avg_change_1d = avg
                        row.positive_rate = _safe_pct(pos, len(deltas))
                        row.negative_rate = _safe_pct(neg, len(deltas))
                        row.details = details
                        row.computed_at = datetime.now(timezone.utc)

                metrics["lifecycle_updates"] = await _apply_pattern_lifecycle_compat(
                    session,
                    lifecycle_thresholds=lifecycle_thresholds,
                )
                metrics["replacement_pressure_post"] = _replacement_pressure_from_inventory(await _pattern_inventory(session))

                accuracy_rows = (
                    await session.execute(
                        select(AccuracyScore)
                        .where(AccuracyScore.period_key == target_period)
                        .order_by(AccuracyScore.agent_name.asc(), AccuracyScore.ticker.asc())
                    )
                ).scalars().all()
                pattern_rows = (
                    await session.execute(select(Pattern).order_by(Pattern.updated_at.desc()).limit(30))
                ).scalars().all()
                impact_rows = (
                    await session.execute(
                        select(ImpactStat).where(ImpactStat.period_key == target_period).order_by(ImpactStat.announcement_type.asc())
                    )
                ).scalars().all()

                human_summary = _build_archive_human_summary(
                    selected_type=selected_type,
                    target_period=target_period,
                    metrics=metrics,
                    upstream_quality=upstream_quality,
                    pattern_rows=pattern_rows,
                    impact_rows=impact_rows,
                )
                metrics["human_summary"] = human_summary
                metrics["human_summary_v2"] = from_archive_summary(summary=human_summary, metrics=metrics)

                artifact_payload = {
                    "metrics": metrics,
                    "human_summary": human_summary,
                    "human_summary_v2": metrics["human_summary_v2"],
                    "global_pattern_context": metrics.get("global_pattern_context") if isinstance(metrics, dict) else {},
                    "accuracy": [
                        {
                            "agent_name": r.agent_name,
                            "ticker": r.ticker,
                            "sample_count": r.sample_count,
                            "accuracy_pct": r.accuracy_pct,
                            "grade": r.grade,
                        }
                        for r in accuracy_rows
                    ],
                    "patterns": [
                        {
                            "ticker": p.ticker,
                            "pattern_type": p.pattern_type,
                            "status": p.status,
                            "occurrence_count": p.occurrence_count,
                            "accuracy_pct": p.accuracy_pct,
                        }
                        for p in pattern_rows
                    ],
                    "impacts": [
                        {
                            "announcement_type": i.announcement_type,
                            "sample_count": i.sample_count,
                            "avg_change_1d": i.avg_change_1d,
                            "positive_rate": i.positive_rate,
                            "negative_rate": i.negative_rate,
                        }
                        for i in impact_rows
                    ],
                }
                html = render_archive_html(
                    run_type=selected_type,
                    period_key=target_period,
                    payload=artifact_payload,
                    human_summary_v2=metrics["human_summary_v2"],
                )
                payload_hash = make_archive_payload_hash(selected_type, target_period, artifact_payload, html)
                subject = build_archive_subject(selected_type, target_period)

                archive = (
                    await session.execute(
                        select(ArchiveRun).where(and_(ArchiveRun.run_type == selected_type, ArchiveRun.period_key == target_period))
                    )
                ).scalar_one_or_none()
                previous_sent_at = archive.email_sent_at if archive else None
                send_allowed = bool(settings.ARCHIVIST_ENABLE_EMAIL_REPORTS)
                force_send_final = bool(force_send if force_send is not None else settings.ARCHIVIST_FORCE_RESEND)
                should_send = send_allowed and (force_send_final or previous_sent_at is None)

                email_sent_at = previous_sent_at
                email_error = None
                archive_status = "generated"
                if should_send:
                    if email_recipients_override:
                        sent, err = send_archive_email(
                            subject=subject,
                            html=html,
                            recipients=email_recipients_override,
                        )
                    else:
                        sent, err = send_archive_email(subject=subject, html=html)
                    metrics["email_sent"] = bool(sent)
                    metrics["email_error"] = err
                    if sent:
                        email_sent_at = datetime.now(timezone.utc)
                        archive_status = "sent"
                    else:
                        email_error = err
                        archive_status = "fail"
                else:
                    metrics["email_skipped"] = True
                    if previous_sent_at is not None:
                        archive_status = "sent"

                summary = {
                    "payload_hash": payload_hash,
                    "subject": subject,
                    **artifact_payload,
                }
                if archive is None:
                    archive = ArchiveRun(
                        run_type=selected_type,
                        period_key=target_period,
                        status=archive_status,
                        summary=summary,
                        html_content=html,
                        email_sent_at=email_sent_at,
                        email_error=email_error,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(archive)
                    created += 1
                else:
                    archive.summary = summary
                    archive.status = archive_status
                    archive.html_content = html
                    archive.email_sent_at = email_sent_at
                    archive.email_error = email_error
                    archive.updated_at = datetime.now(timezone.utc)

                await session.commit()

                try:
                    event_payload = ArchivistPatternsUpdatedV1(
                        run_type=selected_type,  # type: ignore[arg-type]
                        period_key=target_period,
                        patterns_upserted=int(metrics["patterns_upserted"]),
                        impacts_upserted=int(metrics["impacts_upserted"]),
                        accuracy_rows_upserted=int(metrics["accuracy_rows_upserted"]),
                        generated_at=datetime.now(timezone.utc),
                        degraded=bool(metrics["degraded"]),
                    ).model_dump(mode="json")
                    await publish_archivist_patterns_updated(event_payload)
                except Exception as e:  # noqa: PERF203
                    logger.warning("archivist_event_publish_failed", run_id=rid, error=str(e))

        status = "partial" if metrics["degraded"] else "success"
        if metrics["email_error"]:
            status = "fail"
        if status == "success":
            metrics["status_reason"] = "upstream_quality_ok"
        elif status == "partial":
            metrics["status_reason"] = "upstream_degradation_or_low_quality"
        else:
            metrics["status_reason"] = "archive_email_or_pipeline_failure"
        await finish_run(
            rid,
            status=status,
            metrics=metrics,
            records_processed=processed,
            records_new=created,
            errors_count=errors,
        )
        return {"run_id": rid, "status": status, "metrics": metrics}
    except Exception as exc:  # noqa: PERF203
        logger.exception("run_failed", run_id=rid, agent_name="archivist", error=str(exc))
        await fail_run(
            rid,
            error_message=str(exc),
            metrics=metrics,
            records_processed=processed,
            records_new=created,
            errors_count=max(1, errors),
        )
        raise
