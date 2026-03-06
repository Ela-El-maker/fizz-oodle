from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import desc, select
import yaml

from apps.agents.briefing.compute import TickerSummary, compute_change, coverage, rank_movers
from apps.agents.briefing.llm_brief import generate_market_brief, market_brief_to_dict
from apps.agents.briefing.normalize import payload_hash
from apps.agents.briefing.price_sources import fetch_prices_resilient
from apps.agents.briefing.registry import get_briefing_source_configs, get_channel_order
from apps.agents.briefing.source_health import mark_source_failure, mark_source_success
from apps.agents.briefing.sources import (
    fetch_fx_erapi,
    fetch_headlines_bbc_business_rss,
    fetch_headlines_business_daily_html,
    fetch_headlines_html_listing_generic,
    fetch_headlines_google_news_ke,
    fetch_headlines_mystocks,
    fetch_headlines_rss_generic,
    fetch_headlines_sitemap,
    fetch_headlines_standard_business_html,
    fetch_headlines_standard_rss,
    fetch_headlines_the_star_html,
    fetch_index_nasi_resilient,
)
from apps.agents.briefing.store import (
    upsert_daily_briefing,
    upsert_fx,
    upsert_headlines,
    upsert_index,
    upsert_prices,
)
from apps.agents.briefing.types import ForexSnapshot, HeadlinePoint
from apps.core.chart_builder_agent_a import build_agent_a_top_movers_chart
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.email_service import EmailService
from apps.core.global_source_packs import source_allowed_by_pack
from apps.core.logger import get_logger
from apps.core.models import DailyBriefing, FxDaily, IndexDaily, NewsHeadlineDaily, PriceDaily
from apps.core.run_service import fail_run, finish_run, start_run
from apps.core.seed import seed_companies
from apps.reporting.email_digest import build_executive_digest_payload, render_executive_digest_html
from apps.reporting.composer.renderers import from_briefing_summary
from apps.scrape_core.dedupe import content_fingerprint
from apps.scrape_core.retry import classify_error_type

logger = get_logger(__name__)
settings = get_settings()


def _split_csv(value: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in (value or "").split(","):
        src = part.strip().lower()
        if not src or src in seen:
            continue
        seen.add(src)
        ordered.append(src)
    return ordered


def _briefing_date_eat() -> datetime.date:
    now_eat = datetime.now(ZoneInfo("Africa/Nairobi"))
    return now_eat.date()


@lru_cache(maxsize=1)
def _tracked_universe() -> list[dict]:
    cfg = Path(settings.UNIVERSE_CONFIG_PATH)
    if not cfg.is_absolute():
        cfg = (Path(__file__).resolve().parents[3] / settings.UNIVERSE_CONFIG_PATH).resolve()
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    items = data.get("tracked_companies", []) or []
    return [row for row in items if str(row.get("ticker", "")).strip()]


def _nse_scope_universe(rows: list[dict]) -> list[dict]:
    scoped = [r for r in rows if str(r.get("exchange", "NSE")).upper().strip() == "NSE"]
    return scoped or rows


def _build_alias_map(rows: list[dict]) -> dict[str, set[str]]:
    alias_map: dict[str, set[str]] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        aliases = row.get("aliases") or []
        values = {ticker.lower()}
        values.add(str(row.get("company_name") or row.get("name") or ticker).lower())
        for alias in aliases:
            alias_text = str(alias).strip().lower()
            if alias_text:
                values.add(alias_text)
        alias_map[ticker] = values
    return alias_map


def _match_aliases(headline: str, alias_map: dict[str, set[str]]) -> list[str]:
    text = (headline or "").lower()
    matched: list[str] = []
    for ticker, aliases in alias_map.items():
        if any(alias in text for alias in aliases):
            matched.append(ticker)
    return matched


async def _fetch_channel_with_fallback(
    channel: str,
    sources: list[str],
    fetch_map: dict[str, Callable[[], Awaitable[list]]],
):
    if not sources:
        return channel, [], None, None, [], []

    attempted: list[str] = []
    errors: list[str] = []
    failed_sources: list[tuple[str, str, str]] = []
    for source_id in sources:
        fetcher = fetch_map.get(source_id)
        if fetcher is None:
            continue
        attempted.append(source_id)
        try:
            rows = await fetcher()
            return channel, rows, None, source_id, attempted, failed_sources
        except Exception as exc:  # noqa: PERF203
            error_text = str(exc)
            error_type = classify_error_type(exc)
            errors.append(f"{source_id}: {error_text}")
            failed_sources.append((source_id, error_type, error_text))

    if not attempted:
        return channel, [], None, None, [], []
    return channel, [], " | ".join(errors) if errors else "all_sources_failed", None, attempted, failed_sources


async def _collect_news(
    *,
    target_date,
    news_sources: list[str],
    alias_map: dict[str, set[str]],
    source_configs: dict[str, Any],
) -> tuple[list[HeadlinePoint], dict[str, Any]]:
    legacy_fetch_map: dict[str, Callable[[], Awaitable[list[HeadlinePoint]]]] = {
        "standard_rss": lambda: fetch_headlines_standard_rss(target_date),
        "google_news_ke": lambda: fetch_headlines_google_news_ke(target_date),
        "bbc_business_rss": lambda: fetch_headlines_bbc_business_rss(target_date),
        "mystocks": lambda: fetch_headlines_mystocks(target_date),
        "mystocks_news": lambda: fetch_headlines_mystocks(target_date),
        "business_daily_html": lambda: fetch_headlines_business_daily_html(target_date, alias_map),
        "the_star_html": lambda: fetch_headlines_the_star_html(target_date, alias_map),
        "standard_business_html": lambda: fetch_headlines_standard_business_html(target_date, alias_map),
    }
    tasks: dict[str, asyncio.Task] = {}
    source_meta: dict[str, dict[str, Any]] = {}
    for source_id in news_sources:
        cfg = source_configs.get(source_id)
        if cfg is None:
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "unknown_source",
                "error": "source_not_registered",
                "count": 0,
            }
            continue
        if cfg.type == "sitemap" and not settings.ENABLE_SITEMAP_SOURCES:
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "disabled",
                "error": "sitemap_sources_disabled",
                "count": 0,
            }
            continue
        if cfg.scope == "global_outside" and not settings.ENABLE_GLOBAL_OUTSIDE_SOURCES:
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "disabled",
                "error": "global_outside_sources_disabled",
                "count": 0,
            }
            continue
        if not source_allowed_by_pack(
            source_id=cfg.source_id,
            enable_theme_pack=bool(settings.ENABLE_GLOBAL_MARKETS_THEME_PACK),
            enable_extras_pack=bool(settings.ENABLE_GLOBAL_EXTRAS_PACK),
        ):
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "disabled",
                "error": "global_pack_disabled",
                "count": 0,
            }
            continue
        if cfg.premium and not settings.ENABLE_PREMIUM_GLOBAL_SOURCES:
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "disabled",
                "error": "premium_sources_disabled",
                "count": 0,
            }
            continue
        if cfg.type == "html" and not settings.AGENT_A_ENABLE_NEWS_HTML_SOURCES and source_id in {
            "business_daily_html",
            "the_star_html",
            "standard_business_html",
        }:
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "disabled",
                "error": "html_news_sources_disabled",
                "count": 0,
            }
            continue

        fetcher = legacy_fetch_map.get(source_id)
        if fetcher is None:
            item_cap = min(max(1, int(settings.AGENT_A_NEWS_MAX_ITEMS_PER_SOURCE)), max(1, int(cfg.max_items_per_run)))
            if cfg.type == "rss":
                fetcher = lambda cfg=cfg, item_cap=item_cap: fetch_headlines_rss_generic(
                    target_date,
                    source_id=cfg.source_id,
                    rss_url=cfg.base_url,
                    max_items=item_cap,
                )
            elif cfg.type == "sitemap":
                fetcher = lambda cfg=cfg, item_cap=item_cap: fetch_headlines_sitemap(
                    target_date,
                    source_id=cfg.source_id,
                    sitemap_url=cfg.base_url,
                    trust_rank=int(cfg.source_trust_rank),
                    relevance_base=float(cfg.headline_weight),
                    max_items=item_cap,
                )
            elif cfg.type == "html":
                fetcher = lambda cfg=cfg, item_cap=item_cap: fetch_headlines_html_listing_generic(
                    target_date,
                    source_id=cfg.source_id,
                    base_url=cfg.base_url,
                    alias_map=alias_map,
                    trust_rank=int(cfg.source_trust_rank),
                    relevance_base=float(cfg.headline_weight),
                    max_items=item_cap,
                    require_alias_matches=(cfg.scope == "kenya_core"),
                )

        if fetcher is None:
            source_meta[source_id] = {
                "status": "skipped",
                "error_type": "unknown_source",
                "error": "source_not_registered",
                "count": 0,
            }
            continue
        tasks[source_id] = asyncio.create_task(fetcher())

    if tasks:
        raw_results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    else:
        raw_results = []

    merged: list[HeadlinePoint] = []
    for source_id, result in zip(tasks.keys(), raw_results):
        if isinstance(result, Exception):
            source_meta[source_id] = {
                "status": "fail",
                "error_type": classify_error_type(result),
                "error": str(result),
                "count": 0,
            }
            continue
        cfg = source_configs.get(source_id)
        if cfg is not None:
            for row in result:
                payload = dict(row.raw_payload or {})
                payload.update(
                    {
                        "scope": cfg.scope,
                        "market_region": cfg.market_region,
                        "signal_class": cfg.signal_class,
                        "theme": cfg.theme,
                    }
                )
                row.raw_payload = payload
        source_meta[source_id] = {
            "status": "success",
            "error_type": None,
            "error": None,
            "count": len(result),
        }
        merged.extend(result)

    # in-run dedupe + alias filter
    deduped: list[HeadlinePoint] = []
    seen_hashes: set[str] = set()
    for row in merged:
        source_cfg = source_configs.get(row.source_id)
        matched = row.matched_tickers or _match_aliases(row.headline, alias_map)
        keep_without_alias = bool(
            source_cfg is not None and source_cfg.scope in {"kenya_extended", "global_outside"}
        )
        if alias_map and not matched and not keep_without_alias:
            continue
        row.matched_tickers = matched
        hash_value = row.content_hash or content_fingerprint((row.headline or "").strip().lower(), row.url)
        row.content_hash = hash_value
        if hash_value in seen_hashes:
            continue
        seen_hashes.add(hash_value)
        deduped.append(row)

    meta = {
        "sources": source_meta,
        "rows_before_filter": len(merged),
        "rows_after_filter": len(deduped),
    }
    return deduped, meta


async def _load_fx_with_fallback(session, target_date) -> tuple[list, list[ForexSnapshot], dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    snapshots: list[ForexSnapshot] = []
    fx_points = []
    diagnostics: dict[str, Any] = {
        "source_used": None,
        "error": None,
        "status": "missing",
        "pairs": {},
    }

    try:
        fx_points = await fetch_fx_erapi(target_date)
    except Exception as exc:  # noqa: PERF203
        diagnostics["error"] = str(exc)
        fx_points = []

    if fx_points:
        diagnostics["source_used"] = "erapi"
        diagnostics["status"] = "fresh"
        for row in fx_points:
            snapshots.append(
                ForexSnapshot(
                    date=row.date,
                    pair=row.pair,
                    rate=float(row.rate),
                    source_id=row.source_id,
                    status="fresh",
                    age_hours=0.0,
                    confidence=0.95,
                    fetched_at=row.fetched_at,
                    raw_payload=row.raw_payload,
                )
            )
            diagnostics["pairs"][row.pair] = {
                "status": "fresh",
                "confidence": 0.95,
                "age_hours": 0.0,
                "source_id": row.source_id,
            }
        return fx_points, snapshots, diagnostics

    wanted_pairs = ["KES/USD", "KES/EUR"]
    stale_ttl = max(1, int(settings.AGENT_A_FX_STALE_TTL_HOURS))
    hard_ttl = max(stale_ttl, int(settings.AGENT_A_FX_HARD_STALE_TTL_HOURS))

    for pair in wanted_pairs:
        fallback = (
            await session.execute(
                select(FxDaily)
                .where(FxDaily.pair == pair)
                .where(FxDaily.rate.is_not(None))
                .order_by(desc(FxDaily.date), desc(FxDaily.fetched_at))
                .limit(1)
            )
        ).scalars().first()
        if fallback is None:
            snapshots.append(
                ForexSnapshot(
                    date=target_date,
                    pair=pair,
                    rate=None,
                    source_id="db_last_known",
                    status="missing",
                    age_hours=None,
                    confidence=0.0,
                    fetched_at=now_utc,
                    raw_payload=None,
                )
            )
            diagnostics["pairs"][pair] = {
                "status": "missing",
                "confidence": 0.0,
                "age_hours": None,
                "source_id": "db_last_known",
            }
            continue

        fetched_at = fallback.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (now_utc - fetched_at).total_seconds() / 3600.0)

        if age_hours <= stale_ttl:
            confidence = 0.60
            status = "stale_fallback"
        elif age_hours <= hard_ttl:
            confidence = 0.25
            status = "stale_fallback"
        else:
            confidence = 0.25
            status = "stale_fallback"

        snapshots.append(
            ForexSnapshot(
                date=target_date,
                pair=pair,
                rate=float(fallback.rate),
                source_id="db_last_known",
                status=status,
                age_hours=round(age_hours, 2),
                confidence=confidence,
                fetched_at=now_utc,
                raw_payload={
                    "fallback_date": str(fallback.date),
                    "fallback_source_id": fallback.source_id,
                },
            )
        )

        if age_hours <= hard_ttl:
            from apps.agents.briefing.types import FxPoint

            fx_points.append(
                FxPoint(
                    date=target_date,
                    pair=pair,
                    rate=float(fallback.rate),
                    source_id="db_last_known",
                    fetched_at=now_utc,
                    raw_payload={
                        "fallback_date": str(fallback.date),
                        "fallback_source_id": fallback.source_id,
                    },
                )
            )

        diagnostics["pairs"][pair] = {
            "status": status,
            "confidence": confidence,
            "age_hours": round(age_hours, 2),
            "source_id": "db_last_known",
        }

    diagnostics["source_used"] = "db_last_known"
    diagnostics["status"] = "stale_fallback"
    return fx_points, snapshots, diagnostics


def _market_breadth(summaries: list[TickerSummary]) -> dict[str, Any]:
    advancers = len([s for s in summaries if isinstance(s.pct_change, (int, float)) and float(s.pct_change) > 0])
    decliners = len([s for s in summaries if isinstance(s.pct_change, (int, float)) and float(s.pct_change) < 0])
    flat = len([s for s in summaries if isinstance(s.pct_change, (int, float)) and float(s.pct_change) == 0])
    ratio = round(advancers / max(decliners, 1), 4)
    return {
        "advancers_count": advancers,
        "decliners_count": decliners,
        "flat_count": flat,
        "breadth_ratio": ratio,
    }


def _nasi_alignment(*, nasi_pct_change: float | None, breadth_ratio: float) -> str:
    if nasi_pct_change is None:
        return "unknown"
    if nasi_pct_change > 0 and breadth_ratio >= 1:
        return "aligned"
    if nasi_pct_change < 0 and breadth_ratio <= 1:
        return "aligned"
    if nasi_pct_change == 0:
        return "unknown"
    return "diverged"


def _market_regime(*, nasi_pct_change: float | None, breadth_ratio: float) -> str:
    if nasi_pct_change is None:
        return "indecisive"
    if nasi_pct_change > 0.25 and breadth_ratio >= 1.15:
        return "risk_on"
    if nasi_pct_change < -0.25 and breadth_ratio <= 0.9:
        return "risk_off"
    if abs(nasi_pct_change) <= 0.1 and 0.9 <= breadth_ratio <= 1.1:
        return "indecisive"
    return "mixed"


def _risk_score(
    *,
    summaries: list[TickerSummary],
    breadth_ratio: float,
    nasi_alignment: str,
    fx_usd: float | None,
) -> float:
    abs_pcts = [abs(float(s.pct_change)) for s in summaries if isinstance(s.pct_change, (int, float))]
    move_component = min(45.0, (sum(abs_pcts[:10]) / max(len(abs_pcts[:10]), 1)) * 4.0) if abs_pcts else 10.0
    breadth_component = min(25.0, abs(1.0 - breadth_ratio) * 25.0)
    alignment_component = 15.0 if nasi_alignment == "diverged" else 5.0
    fx_component = 0.0
    if isinstance(fx_usd, (int, float)):
        # pair in this system is KES/USD; stress when unusually low conversion value.
        if fx_usd < 0.007:
            fx_component = 15.0
        elif fx_usd < 0.0075:
            fx_component = 10.0
        else:
            fx_component = 5.0
    score = round(min(100.0, move_component + breadth_component + alignment_component + fx_component), 2)
    return score


def _build_briefing_human_summary(
    *,
    market_brief,
    summaries: list[TickerSummary],
    breadth: dict[str, Any],
    nasi_pct: float | None,
    nasi_alignment: str,
    regime: str,
    risk: float,
    fx_snapshots: list[ForexSnapshot],
) -> dict[str, Any]:
    movers = sorted(
        [s for s in summaries if isinstance(s.pct_change, (int, float))],
        key=lambda x: abs(float(x.pct_change or 0.0)),
        reverse=True,
    )[:3]
    top_movers = [
        {
            "ticker": m.ticker,
            "pct_change": round(float(m.pct_change or 0.0), 2),
            "direction": "up" if float(m.pct_change or 0.0) > 0 else ("down" if float(m.pct_change or 0.0) < 0 else "flat"),
        }
        for m in movers
    ]
    top_movers_line = (
        "Top movers: " + "; ".join(f"{m['ticker']} ({m['pct_change']:+.2f}%)" for m in top_movers)
        if top_movers
        else "Top movers: no price movers available."
    )

    fx_line_parts: list[str] = []
    for snap in fx_snapshots:
        if snap.rate is None:
            fx_line_parts.append(f"{snap.pair}: unavailable")
            continue
        freshness = f"{snap.status}" + (f", {snap.age_hours:.1f}h old" if isinstance(snap.age_hours, (int, float)) else "")
        fx_line_parts.append(f"{snap.pair}: {snap.rate:.6f} ({freshness})")
    fx_line = "FX freshness: " + ("; ".join(fx_line_parts) if fx_line_parts else "not available.")

    regime_text = regime.replace("_", " ")
    alignment_text = nasi_alignment.replace("_", " ")
    breadth_line = (
        f"Breadth: {int(breadth.get('advancers_count', 0))} advancers, "
        f"{int(breadth.get('decliners_count', 0))} decliners, "
        f"{int(breadth.get('flat_count', 0))} flat (ratio {float(breadth.get('breadth_ratio', 0.0)):.2f})."
    )
    nasi_line = (
        f"NASI move: {nasi_pct:+.2f}% with {alignment_text} breadth."
        if isinstance(nasi_pct, (int, float))
        else "NASI move: unavailable."
    )
    risk_line = f"Regime: {regime_text}. Market risk score: {risk:.2f}/100."

    drivers = [str(d) for d in (market_brief.drivers or []) if str(d).strip()]
    unusual = [str(u) for u in (market_brief.unusual_signals or []) if str(u).strip()]
    model_conf = (
        f"Model confidence: {market_brief.confidence_level} ({float(market_brief.confidence_score):.2f})"
        f" via {market_brief.provider}/{market_brief.model}."
    )

    bullets = [breadth_line, nasi_line, risk_line, top_movers_line, fx_line]
    bullets.extend(drivers[:2])
    bullets.extend(unusual[:2])
    bullets.append(model_conf)

    return {
        "headline": str(market_brief.market_pulse or "Daily market pulse is available."),
        "plain_summary": str(market_brief.narrative_interpretation or ""),
        "bullets": bullets,
        "regime": regime,
        "risk_score": risk,
        "nasi_alignment": nasi_alignment,
        "top_movers": top_movers,
        "confidence": {
            "level": market_brief.confidence_level,
            "score": float(market_brief.confidence_score),
            "reason": market_brief.confidence_reason,
            "llm_used": bool(market_brief.llm_used),
            "llm_error": market_brief.llm_error,
        },
    }


async def run_daily_briefing_pipeline(
    run_id: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
) -> dict:
    rid = await start_run("briefing", run_id=run_id)
    await seed_companies()
    force_send_final = bool(force_send if force_send is not None else settings.DAILY_BRIEFING_FORCE_SEND)

    target_date = _briefing_date_eat()
    universe_rows = _nse_scope_universe(_tracked_universe())
    tickers = [str(row.get("ticker", "")).upper().strip() for row in universe_rows if str(row.get("ticker", "")).strip()]
    if not tickers:
        raise RuntimeError("Tracked NSE universe is empty; check config/universe.yml")

    company_name_by_ticker = {
        str(row.get("ticker", "")).upper().strip(): str(row.get("company_name") or row.get("name") or row.get("ticker")).strip()
        for row in universe_rows
        if str(row.get("ticker", "")).strip()
    }
    alias_map = _build_alias_map(universe_rows)

    metrics: dict[str, Any] = {
        "target_date": target_date.isoformat(),
        "channels": {},
        "channel_errors": {},
        "channel_quality": {},
        "email_sent": False,
        "email_skipped": False,
        "email_error": None,
    }

    try:
        price_sources = _split_csv(settings.ENABLED_PRICE_SOURCES)
        idx_sources = _split_csv(settings.ENABLED_INDEX_SOURCES)
        fx_sources = _split_csv(settings.ENABLED_FX_SOURCES)
        news_sources = _split_csv(settings.ENABLED_NEWS_SOURCES)
        source_registry = get_briefing_source_configs()
        channel_order = get_channel_order()

        if not price_sources:
            price_sources = channel_order.get("prices", ["alpha_vantage", "mystocks", "nse_market_stats_prices"])
        if not idx_sources:
            idx_sources = channel_order.get("index", ["nse_market_stats", "mystocks"])
        if not fx_sources:
            fx_sources = channel_order.get("fx", ["erapi"])
        if not news_sources:
            news_sources = channel_order.get("news", ["standard_rss", "google_news_ke", "bbc_business_rss", "mystocks_news"])

        def _filter_enabled(channel: str, source_ids: list[str]) -> list[str]:
            out: list[str] = []
            for source_id in source_ids:
                cfg = source_registry.get(source_id)
                if cfg is None:
                    continue
                if cfg.channel != channel:
                    continue
                if not cfg.enabled_by_default:
                    continue
                if cfg.type == "sitemap" and not settings.ENABLE_SITEMAP_SOURCES:
                    continue
                if cfg.scope == "global_outside" and not settings.ENABLE_GLOBAL_OUTSIDE_SOURCES:
                    continue
                if not source_allowed_by_pack(
                    source_id=cfg.source_id,
                    enable_theme_pack=bool(settings.ENABLE_GLOBAL_MARKETS_THEME_PACK),
                    enable_extras_pack=bool(settings.ENABLE_GLOBAL_EXTRAS_PACK),
                ):
                    continue
                if cfg.premium and not settings.ENABLE_PREMIUM_GLOBAL_SOURCES:
                    continue
                out.append(source_id)
            return out

        price_sources = _filter_enabled("prices", price_sources)
        idx_sources = _filter_enabled("index", idx_sources)
        fx_sources = _filter_enabled("fx", fx_sources)
        news_sources = _filter_enabled("news", news_sources)

        channel_errors: dict[str, str] = {}
        channel_quality: dict[str, dict[str, Any]] = {}
        inserted_counts = {"prices": 0, "index": 0, "fx": 0, "news": 0}

        async with get_session() as session:
            now_utc = datetime.now(timezone.utc)

            # Prices: resilient per-ticker source chain.
            prices, normalized_prices, price_diag = await fetch_prices_resilient(
                target_date=target_date,
                universe_rows=universe_rows,
                source_order=price_sources,
                session=session,
            )
            metrics["channels"]["prices"] = {
                "count": len(prices),
                "source_order": price_sources,
                "source_stats": price_diag.get("source_stats", {}),
                "missing_tickers": price_diag.get("missing_tickers", []),
                "ticker_failures": price_diag.get("ticker_failures", {}),
            }
            channel_quality["prices"] = {
                "tier": "core",
                "required_for_success": True,
                "status": "success" if prices else "fail",
                "count": len(prices),
                "error": None if prices else "all_sources_failed",
                "source_order": price_sources,
            }
            if not prices:
                channel_errors["prices"] = "all_sources_failed"

            # Mark source health for price sources.
            for source_id, stats in (price_diag.get("source_stats") or {}).items():
                attempted = int(stats.get("attempted") or 0)
                success = int(stats.get("success") or 0)
                failed = int(stats.get("failed") or 0)
                if attempted <= 0:
                    continue
                if success > 0:
                    await mark_source_success(
                        session=session,
                        source_id=source_id,
                        metrics={
                            "channel": "prices",
                            "attempted": attempted,
                            "success": success,
                            "failed": failed,
                        },
                        now_utc=now_utc,
                    )
                if failed > 0 and success == 0:
                    failures = []
                    for _ticker, detail_rows in (price_diag.get("ticker_failures") or {}).items():
                        for detail in detail_rows:
                            if detail.get("source_id") == source_id:
                                failures.append(detail)
                    if failures:
                        most_common = Counter([str(row.get("error_type") or "unknown_error") for row in failures]).most_common(1)[0][0]
                        sample_error = str(failures[0].get("error") or "source_failed")
                    else:
                        most_common = "unknown_error"
                        sample_error = "source_failed"
                    await mark_source_failure(
                        session=session,
                        source_id=source_id,
                        error=sample_error,
                        error_type=most_common,
                        now_utc=now_utc,
                        fail_threshold=settings.SOURCE_FAIL_THRESHOLD,
                        cooldown_minutes=settings.SOURCE_COOLDOWN_MINUTES,
                    )

            # Index: resilient NASI-focused extraction, non-blocking.
            index_rows, index_diag = await fetch_index_nasi_resilient(target_date)
            metrics["channels"]["index"] = {
                "count": len(index_rows),
                "source_used": index_diag.get("source_used"),
                "status": index_diag.get("status"),
                "error": index_diag.get("error"),
                "attempted_sources": idx_sources,
            }
            channel_quality["index"] = {
                "tier": "core",
                "required_for_success": True,
                "status": "success" if index_rows else "fail",
                "count": len(index_rows),
                "source_used": index_diag.get("source_used"),
                "error": index_diag.get("error"),
            }
            if not index_rows:
                channel_errors.setdefault("index", "index_unavailable")
            source_used = index_diag.get("source_used")
            if source_used and index_rows:
                await mark_source_success(
                    session=session,
                    source_id=str(source_used),
                    metrics={"channel": "index", "count": len(index_rows), "status": "success"},
                    now_utc=now_utc,
                )

            # FX: primary source with DB fallback.
            fx_rows, fx_snapshots, fx_diag = await _load_fx_with_fallback(session, target_date)
            metrics["channels"]["fx"] = {
                "count": len(fx_rows),
                "source_used": fx_diag.get("source_used"),
                "status": fx_diag.get("status"),
                "error": fx_diag.get("error"),
                "pairs": fx_diag.get("pairs"),
                "attempted_sources": fx_sources,
            }
            channel_quality["fx"] = {
                "tier": "core",
                "required_for_success": True,
                "status": "success" if fx_rows else "fail",
                "count": len(fx_rows),
                "source_used": fx_diag.get("source_used"),
                "error": fx_diag.get("error"),
            }
            if not fx_rows:
                channel_errors.setdefault("fx", "fx_unavailable")
            if fx_diag.get("source_used") == "erapi" and fx_rows:
                await mark_source_success(
                    session=session,
                    source_id="erapi",
                    metrics={"channel": "fx", "count": len(fx_rows), "status": "success"},
                    now_utc=now_utc,
                )
            elif fx_diag.get("error"):
                await mark_source_failure(
                    session=session,
                    source_id="erapi",
                    error=str(fx_diag.get("error")),
                    error_type="upstream_error",
                    now_utc=now_utc,
                    fail_threshold=settings.SOURCE_FAIL_THRESHOLD,
                    cooldown_minutes=settings.SOURCE_COOLDOWN_MINUTES,
                )

            # News: gather all configured sources in parallel (non-core).
            headlines, news_meta = await _collect_news(
                target_date=target_date,
                news_sources=news_sources,
                alias_map=alias_map,
                source_configs=source_registry,
            )
            metrics["channels"]["news"] = {
                "count": len(headlines),
                "attempted_sources": news_sources,
                "sources": news_meta.get("sources", {}),
                "rows_before_filter": news_meta.get("rows_before_filter", 0),
                "rows_after_filter": news_meta.get("rows_after_filter", 0),
            }
            global_news = [
                row
                for row in headlines
                if isinstance(row.raw_payload, dict) and str(row.raw_payload.get("scope") or "") == "global_outside"
            ]
            theme_counter = Counter(
                str((row.raw_payload or {}).get("theme") or "unknown").strip().lower()
                for row in global_news
                if isinstance(row.raw_payload, dict)
            )
            metrics["global_news_collected"] = len(global_news)
            metrics["global_themes"] = [
                {"theme": theme, "count": count}
                for theme, count in sorted(theme_counter.items(), key=lambda item: item[1], reverse=True)
            ]
            metrics["source_health_by_source_id"] = {
                sid: {
                    "status": str(meta.get("status") or "unknown"),
                    "count": int(meta.get("count") or 0),
                    "error_type": meta.get("error_type"),
                    "error": meta.get("error"),
                }
                for sid, meta in (news_meta.get("sources") or {}).items()
            }
            news_errors = [
                f"{sid}:{meta.get('error_type')}"
                for sid, meta in (news_meta.get("sources") or {}).items()
                if meta.get("status") == "fail"
            ]
            channel_quality["news"] = {
                "tier": "secondary",
                "required_for_success": False,
                "status": "success" if headlines else ("degraded" if news_errors else "empty"),
                "count": len(headlines),
                "error": " | ".join(news_errors) if news_errors else None,
            }
            # news failures are surfaced but do not make run partial by themselves.
            for source_id, meta in (news_meta.get("sources") or {}).items():
                status = str(meta.get("status") or "").lower()
                if status == "success" and int(meta.get("count") or 0) > 0:
                    await mark_source_success(
                        session=session,
                        source_id=source_id,
                        metrics={"channel": "news", "count": int(meta.get("count") or 0), "status": "success"},
                        now_utc=now_utc,
                    )
                elif status == "fail":
                    await mark_source_failure(
                        session=session,
                        source_id=source_id,
                        error=str(meta.get("error") or "source_failed"),
                        error_type=str(meta.get("error_type") or "unknown_error"),
                        now_utc=now_utc,
                        fail_threshold=settings.SOURCE_FAIL_THRESHOLD,
                        cooldown_minutes=settings.SOURCE_COOLDOWN_MINUTES,
                    )

            inserted_counts["prices"] = await upsert_prices(session, prices)
            inserted_counts["index"] = await upsert_index(session, index_rows)
            inserted_counts["fx"] = await upsert_fx(session, fx_rows)
            inserted_counts["news"] = await upsert_headlines(session, headlines)
            await session.commit()

            current_prices = (
                await session.execute(select(PriceDaily).where(PriceDaily.date == target_date).order_by(PriceDaily.ticker))
            ).scalars().all()

            summaries: list[TickerSummary] = []
            for row in current_prices:
                prev = (
                    await session.execute(
                        select(PriceDaily)
                        .where(PriceDaily.ticker == row.ticker)
                        .where(PriceDaily.date < target_date)
                        .order_by(desc(PriceDaily.date))
                        .limit(1)
                    )
                ).scalars().first()
                prev_close = float(prev.close) if prev and prev.close is not None else None
                close = float(row.close) if row.close is not None else None
                change, pct = compute_change(close, prev_close)
                summaries.append(
                    TickerSummary(
                        ticker=row.ticker,
                        close=close,
                        prev_close=prev_close,
                        change=change,
                        pct_change=pct,
                        volume=float(row.volume) if row.volume is not None else None,
                    )
                )

            gainers, losers = rank_movers(summaries, top_n=6)
            nasi = (
                await session.execute(
                    select(IndexDaily)
                    .where(IndexDaily.date == target_date)
                    .where(IndexDaily.index_name == "NASI")
                    .limit(1)
                )
            ).scalars().first()
            fx_map = {
                row.pair: float(row.rate)
                for row in (await session.execute(select(FxDaily).where(FxDaily.date == target_date))).scalars().all()
            }
            headline_rows = (
                await session.execute(
                    select(NewsHeadlineDaily)
                    .where(NewsHeadlineDaily.date == target_date)
                    .order_by(NewsHeadlineDaily.fetched_at.desc())
                    .limit(12)
                )
            ).scalars().all()

            coverage_stats = coverage(
                expected_tickers=len(tickers),
                captured_tickers=len({s.ticker for s in summaries if s.close is not None}),
                has_index=nasi is not None,
                fx_pairs=len(fx_map),
            )
            min_coverage = max(0.0, min(1.0, float(settings.AGENT_A_MIN_PRICE_COVERAGE_PCT))) * 100.0
            if coverage_stats["ticker_coverage_pct"] < min_coverage:
                channel_errors["prices"] = "price_coverage_low"
                channel_quality["prices"]["status"] = "degraded"
                channel_quality["prices"]["error"] = "price_coverage_low"

            breadth = _market_breadth(summaries)
            nasi_pct = float(nasi.pct_change) if nasi and nasi.pct_change is not None else None
            nasi_align = _nasi_alignment(nasi_pct_change=nasi_pct, breadth_ratio=float(breadth["breadth_ratio"]))
            regime = _market_regime(nasi_pct_change=nasi_pct, breadth_ratio=float(breadth["breadth_ratio"]))
            risk = _risk_score(
                summaries=summaries,
                breadth_ratio=float(breadth["breadth_ratio"]),
                nasi_alignment=nasi_align,
                fx_usd=fx_map.get("KES/USD"),
            )

            chart_input = [
                {"ticker": s.ticker, "pct_change": s.pct_change, "volume": s.volume}
                for s in summaries
                if s.pct_change is not None
            ]
            chart_result = build_agent_a_top_movers_chart(
                rows=chart_input,
                target_date=target_date,
                output_dir=settings.AGENT_A_CHART_OUTPUT_DIR,
                nasi_value=float(nasi.value) if nasi and nasi.value is not None else None,
                nasi_pct=nasi_pct,
                volume_overlay=bool(settings.AGENT_A_CHART_ENABLE_VOLUME_OVERLAY),
                top_n=10,
            )

            llm_context = {
                "target_date": target_date.isoformat(),
                "top_movers": [
                    {
                        "ticker": item.ticker,
                        "pct_change": float(item.pct_change) if item.pct_change is not None else None,
                        "volume": float(item.volume) if item.volume is not None else None,
                    }
                    for item in sorted(summaries, key=lambda x: abs(float(x.pct_change or 0.0)), reverse=True)[:5]
                ],
                "market_breadth": breadth,
                "nasi": {
                    "value": float(nasi.value) if nasi and nasi.value is not None else None,
                    "pct_change": nasi_pct,
                    "alignment": nasi_align,
                },
                "fx": {
                    "KES/USD": fx_map.get("KES/USD"),
                    "KES/EUR": fx_map.get("KES/EUR"),
                    "snapshots": [
                        {
                            "pair": fxs.pair,
                            "status": fxs.status,
                            "confidence": fxs.confidence,
                            "age_hours": fxs.age_hours,
                        }
                        for fxs in fx_snapshots
                    ],
                },
                "risk_score": risk,
                "headlines": [
                    {"headline": h.headline, "url": h.url}
                    for h in sorted(
                        headlines,
                        key=lambda row: (row.relevance_score, row.confidence),
                        reverse=True,
                    )[:3]
                ],
                "unusual_signals": [
                    "NASI and breadth divergence detected" if nasi_align == "diverged" else "No major divergence detected"
                ],
            }
            market_brief, brief_text = await generate_market_brief(llm_context)
            human_summary = _build_briefing_human_summary(
                market_brief=market_brief,
                summaries=summaries,
                breadth=breadth,
                nasi_pct=nasi_pct,
                nasi_alignment=nasi_align,
                regime=regime,
                risk=risk,
                fx_snapshots=fx_snapshots,
            )
            human_summary_v2 = from_briefing_summary(summary=human_summary, metrics=metrics)

            metrics["coverage"] = coverage_stats
            metrics["inserted"] = inserted_counts
            metrics["channel_errors"] = channel_errors
            metrics["channel_quality"] = channel_quality
            metrics["price_diagnostics"] = {
                "missing_tickers": price_diag.get("missing_tickers", []),
                "source_stats": price_diag.get("source_stats", {}),
            }
            metrics["market_breadth"] = breadth
            metrics["nasi_alignment"] = nasi_align
            metrics["market_regime"] = regime
            metrics["risk_score"] = risk
            metrics["llm_brief_json"] = market_brief_to_dict(market_brief)
            metrics["llm_brief_text"] = brief_text
            metrics["llm_error"] = market_brief.llm_error
            metrics["human_summary"] = human_summary
            metrics["human_summary_v2"] = human_summary_v2
            metrics["chart_generated"] = chart_result.generated
            metrics["chart_path"] = chart_result.path
            metrics["chart_error"] = chart_result.error

            env = Environment(loader=FileSystemLoader("templates"))
            template = env.get_template("briefing.html")
            legacy_subject = f"📈 NSE Daily Briefing — {target_date.isoformat()}"
            legacy_html = template.render(
                date=target_date.isoformat(),
                nasi_value=f"{float(nasi.value):.2f}" if nasi and nasi.value is not None else "N/A",
                nasi_pct=f"{float(nasi.pct_change):.2f}" if nasi and nasi.pct_change is not None else "N/A",
                kes_usd=f"{fx_map.get('KES/USD', 'N/A')}",
                kes_eur=f"{fx_map.get('KES/EUR', 'N/A')}",
                rows=[
                    {
                        "ticker": s.ticker,
                        "name": company_name_by_ticker.get(s.ticker, s.ticker),
                        "price": f"{s.close:.2f}" if s.close is not None else "N/A",
                        "pct_change": f"{s.pct_change:.2f}" if s.pct_change is not None else "N/A",
                    }
                    for s in summaries
                ],
                top_movers_chart_b64=chart_result.b64_png,
                summary=brief_text,
                human_summary=human_summary,
                human_summary_v2=human_summary_v2,
                headlines=[{"headline": h.headline, "url": h.url} for h in headline_rows],
            )

            existing_briefing = (
                await session.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == target_date))
            ).scalars().first()
            existing_metrics = existing_briefing.metrics if existing_briefing and isinstance(existing_briefing.metrics, dict) else {}

            exec_enabled = bool(settings.EMAIL_EXEC_DIGEST_ENABLED)
            parallel_legacy = bool(settings.EMAIL_EXEC_DIGEST_PARALLEL_LEGACY) and int(settings.EMAIL_EXEC_DIGEST_PARALLEL_DAYS) > 0
            legacy_enabled = (not exec_enabled) or parallel_legacy or force_send_final
            metrics["executive_digest_parallel_legacy"] = parallel_legacy
            metrics["executive_digest_parallel_days"] = int(settings.EMAIL_EXEC_DIGEST_PARALLEL_DAYS)

            should_send_legacy = legacy_enabled
            if existing_briefing and existing_briefing.email_sent_at and not force_send_final:
                should_send_legacy = False
                metrics["email_skipped"] = True
            if not legacy_enabled:
                metrics["email_skipped"] = True
                metrics["email_skipped_reason"] = "legacy_cutover_enabled"

            should_send_exec = False
            if exec_enabled:
                should_send_exec = force_send_final or not bool(existing_metrics.get("executive_digest_sent_at"))

            executive_payload = None
            executive_subject = f"Market Intel Daily — {target_date.isoformat()} | Kenya Core + Global Outside"
            executive_html = None
            if exec_enabled:
                summary_quality = (
                    human_summary_v2.get("quality")
                    if isinstance(human_summary_v2, dict) and isinstance(human_summary_v2.get("quality"), dict)
                    else {}
                )
                executive_payload = await build_executive_digest_payload(
                    session,
                    target_date=target_date,
                    a_context={
                        "headline": human_summary_v2.get("headline") if isinstance(human_summary_v2, dict) else human_summary.get("headline"),
                        "summary": human_summary_v2.get("plain_summary") if isinstance(human_summary_v2, dict) else brief_text,
                        "confidence_score": summary_quality.get("confidence_score", 0.6),
                        "headlines": [{"headline": h.headline, "url": h.url} for h in headline_rows[:10]],
                        "next_watch": human_summary_v2.get("next_watch") if isinstance(human_summary_v2, dict) else [],
                        "top_movers": llm_context.get("top_movers", []),
                        "coverage_pct": coverage_stats.get("ticker_coverage_pct", 0.0),
                        "llm_error": market_brief.llm_error,
                    },
                    max_stories=max(4, int(settings.EMAIL_EXEC_DIGEST_MAX_STORIES)),
                    use_agent_f=bool(settings.EMAIL_EXEC_DIGEST_USE_AGENT_F),
                    include_glossary=bool(settings.EMAIL_EXEC_DIGEST_INCLUDE_GLOSSARY),
                )
                executive_html = render_executive_digest_html(executive_payload)
                metrics["executive_digest_story_count"] = len(executive_payload.get("inside_kenya", [])) + len(
                    executive_payload.get("outside_kenya", [])
                )
                metrics["executive_digest_sections"] = [
                    "one_minute",
                    "inside_kenya",
                    "outside_kenya",
                    "global_to_kenya",
                    "watchlist",
                    "read_more",
                ]
            else:
                metrics["executive_digest_story_count"] = 0
                metrics["executive_digest_sections"] = []

            legacy_sent_at = None
            legacy_error = None
            exec_sent_at = None
            exec_error = None

            if should_send_legacy:
                try:
                    send_result = EmailService().send(
                        subject=legacy_subject,
                        html=legacy_html,
                        recipients=email_recipients_override if email_recipients_override else None,
                    )
                    legacy_sent_at = datetime.now(timezone.utc)
                    metrics["email_sent"] = True
                    metrics["email_mode"] = send_result.mode
                    metrics["email_provider"] = send_result.provider
                except Exception as exc:  # noqa: PERF203
                    legacy_error = str(exc)
                    metrics["email_error"] = legacy_error
            else:
                metrics["email_sent"] = bool(existing_briefing and existing_briefing.email_sent_at)

            metrics["executive_digest_enabled"] = exec_enabled
            metrics["executive_digest_sent"] = False
            metrics["executive_digest_error"] = None
            metrics["executive_digest_subject"] = executive_subject if exec_enabled else None
            if should_send_exec and executive_html:
                try:
                    EmailService().send(
                        subject=executive_subject,
                        html=executive_html,
                        recipients=email_recipients_override if email_recipients_override else None,
                    )
                    exec_sent_at = datetime.now(timezone.utc)
                    metrics["executive_digest_sent"] = True
                    metrics["executive_digest_sent_at"] = exec_sent_at.isoformat()
                except Exception as exc:  # noqa: PERF203
                    exec_error = str(exc)
                    metrics["executive_digest_error"] = exec_error
            elif exec_enabled and existing_metrics.get("executive_digest_sent_at"):
                metrics["executive_digest_sent"] = True
                metrics["executive_digest_sent_at"] = existing_metrics.get("executive_digest_sent_at")

            metrics["email_sent"] = bool(metrics.get("email_sent") or metrics.get("executive_digest_sent"))

            selected_subject = executive_subject if exec_enabled and executive_html else legacy_subject
            selected_html = executive_html if exec_enabled and executive_html else legacy_html
            p_hash = payload_hash(selected_html)

            primary_sent_at = exec_sent_at or legacy_sent_at
            if primary_sent_at is None and existing_briefing and existing_briefing.email_sent_at:
                primary_sent_at = existing_briefing.email_sent_at

            email_error = exec_error or legacy_error
            if email_error:
                metrics["email_error"] = email_error
            if email_error:
                briefing_status = "fail"
            elif primary_sent_at:
                briefing_status = "sent"
            else:
                briefing_status = "generated"

            await upsert_daily_briefing(
                session,
                briefing_date=target_date,
                subject=selected_subject,
                html_content=selected_html,
                payload_hash=p_hash,
                status=briefing_status,
                metrics=metrics,
                email_sent_at=primary_sent_at,
                email_error=email_error,
            )
            await session.commit()

        core_failures = [name for name in ("prices", "index", "fx") if name in channel_errors]
        status = "success"
        if core_failures:
            status = "partial"
        if metrics.get("email_error") or metrics.get("executive_digest_error"):
            status = "fail"

        if status == "success":
            metrics["status_reason"] = "all_core_channels_healthy"
        elif status == "partial":
            metrics["status_reason"] = "core_channel_degradation"
        else:
            metrics["status_reason"] = "email_or_pipeline_failure"

        await finish_run(
            rid,
            status=status,
            records_processed=(
                int(metrics["channels"].get("prices", {}).get("count", 0))
                + int(metrics["channels"].get("index", {}).get("count", 0))
                + int(metrics["channels"].get("fx", {}).get("count", 0))
                + int(metrics["channels"].get("news", {}).get("count", 0))
            ),
            records_new=sum(inserted_counts.values()),
            errors_count=len(core_failures)
            + (1 if metrics.get("email_error") else 0)
            + (1 if metrics.get("executive_digest_error") else 0),
            metrics=metrics,
            error_message=metrics.get("executive_digest_error") or metrics.get("email_error"),
        )

        return {
            "run_id": rid,
            "status": status,
            "target_date": target_date.isoformat(),
            "metrics": metrics,
        }

    except Exception as exc:
        logger.exception("run_failed", run_id=rid, agent_name="briefing", error=str(exc))
        await fail_run(rid, error_message=str(exc), metrics=metrics, errors_count=1)
        raise
