from __future__ import annotations

import asyncio
from datetime import timezone
import time

import httpx
from apps.agents.announcements.classify import CLASSIFIER_VERSION, classify_announcement
from apps.agents.announcements.email import send_announcements_email
from apps.agents.announcements.enrich import extract_details
from apps.agents.announcements.hashing import make_announcement_id, make_content_hash
from apps.agents.announcements.normalize import NORMALIZER_VERSION, canonicalize_url, normalize_headline, parse_datetime_to_utc, utc_now
from apps.agents.announcements.registry import get_collector, get_source_configs
from apps.agents.announcements.resolve_ticker import resolve_company_name, resolve_ticker
from apps.agents.announcements.severity import derive_severity
from apps.agents.announcements.sources.common import SourceFetchError, bind_http_client, classify_source_error
from apps.agents.announcements.store import (
    content_hash_exists,
    list_alert_candidates,
    load_known_announcement_keys,
    list_recent_announcements_for_validation,
    mark_alerted,
    mark_source_failure,
    mark_source_success,
    source_can_run,
    upsert_announcements_batch,
)
from apps.agents.announcements.types import NormalizedAnnouncement, SourceConfig
from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.logger import get_logger
from apps.core.alpha_vantage import fetch_alpha_quote_batch
from apps.core.run_service import fail_run, finish_run, start_run
from apps.core.seed import seed_companies
from apps.reporting.composer.renderers import from_announcements_summary

logger = get_logger(__name__)
settings = get_settings()

KENYA_IMPACT_SECTOR_MAP: dict[str, list[str]] = {
    "oil": ["energy", "transport", "manufacturing", "consumer"],
    "commodities": ["energy", "manufacturing", "consumer", "agriculture"],
    "usd_strength": ["banking", "energy", "manufacturing", "consumer"],
    "bonds_yields": ["banking", "consumer", "industrials"],
    "earnings_cycle": ["banking", "consumer", "industrials", "telecom"],
    "dividends_flow": ["banking", "consumer", "telecom", "industrials"],
    "global_equities_trading": ["banking", "consumer", "industrials"],
    "global_risk": ["banking", "consumer", "industrials"],
    "ai_platforms": ["telecom", "media", "technology", "education"],
    "ai_research": ["technology", "telecom", "education"],
    "global_tech_risk": ["telecom", "technology", "media", "education"],
    "global_macro": ["banking", "consumer", "industrials"],
    "kenya_business_news": ["banking", "consumer", "industrials", "energy"],
}

KENYA_IMPACT_CHANNEL_MAP: dict[str, list[str]] = {
    "oil": ["fuel_costs", "shipping_logistics", "inflation", "import_costs"],
    "commodities": ["input_costs", "inflation", "trade_terms"],
    "usd_strength": ["fx_pressure", "import_costs", "inflation", "liquidity"],
    "bonds_yields": ["banking_liquidity", "credit_cost", "capital_flows", "fx_pressure"],
    "earnings_cycle": ["equity_valuation", "investor_positioning", "capital_rotation"],
    "dividends_flow": ["income_rotation", "yield_repricing", "capital_rotation"],
    "global_equities_trading": ["risk_appetite", "capital_flows", "sector_rotation"],
    "global_risk": ["risk_appetite", "capital_flows", "liquidity"],
    "ai_platforms": ["tech_spend", "cloud_adoption", "automation", "productivity"],
    "ai_research": ["productivity", "cloud_adoption", "innovation_cycle"],
    "global_tech_risk": ["tech_spend", "cloud_adoption", "automation", "platform_risk"],
    "global_macro": ["risk_appetite", "capital_flows", "liquidity"],
    "kenya_business_news": ["investor_positioning", "sector_rotation", "earnings_expectations"],
}

THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oil": ("oil", "brent", "crude", "opec", "fuel", "shipping", "freight", "port"),
    "commodities": ("commodity", "commodities", "metals", "agri", "agriculture", "fertilizer"),
    "usd_strength": ("usd", "u.s. dollar", "dollar index", "fed", "federal reserve", "fx", "forex"),
    "bonds_yields": ("bond", "bonds", "yield", "yields", "treasury", "coupon", "sovereign debt"),
    "earnings_cycle": ("earnings", "guidance", "profit warning", "quarterly results", "eps"),
    "dividends_flow": ("dividend", "payout", "book closure", "yield"),
    "global_equities_trading": ("stocks", "equities", "trading", "index", "risk off", "risk-on", "selloff", "rally"),
    "global_risk": ("volatility", "risk off", "risk-on", "drawdown", "flight to safety"),
    "ai_platforms": ("ai", "openai", "deepmind", "anthropic", "llm", "model release", "gpu", "inference"),
    "ai_research": ("ai research", "benchmark", "model", "training", "inference", "compute"),
    "global_tech_risk": ("ai", "openai", "deepmind", "anthropic", "chip", "gpu", "cloud", "platform"),
    "kenya_business_news": ("kenya", "nairobi", "nse", "cbk", "cma", "earnings", "dividend"),
}


def derive_announcements_status(
    *,
    core_failures: int,
    source_failures: int,
    source_successes: int,
    new_alert_count: int,
    email_sent: bool,
) -> str:
    status = "success"
    if core_failures > 0:
        status = "partial" if source_successes > 0 else "fail"
    elif source_failures > 0 and source_successes == 0:
        status = "fail"
    if new_alert_count > 0 and not email_sent:
        return "fail" if status == "success" else "partial"
    return status


def _infer_theme(
    *,
    text: str,
    source_theme: str | None,
) -> str | None:
    if source_theme:
        return source_theme.strip().lower()
    lowered = text.lower()
    for theme, terms in THEME_KEYWORDS.items():
        if any(term in lowered for term in terms):
            return theme
    return None


def _kenya_impact_score(
    *,
    source: SourceConfig,
    ticker: str | None,
    company_name: str | None,
    headline: str,
    details: str | None,
    announcement_type: str,
    type_confidence: float,
    theme: str | None,
) -> int:
    if source.scope != "global_outside":
        return 100

    text = f"{headline} {details or ''}".lower()
    score = 5.0
    weight = max(0.1, float(source.kenya_impact_weight or 1.0))
    if ticker:
        score += 35.0
    if company_name:
        score += 10.0

    kenya_tokens = ("kenya", "nairobi", "east africa", "mombasa", "nse", "cbk", "cma")
    if any(token in text for token in kenya_tokens):
        score += 25.0

    if announcement_type not in {"other", "unknown"}:
        score += 10.0

    if theme in {
        "oil",
        "commodities",
        "usd_strength",
        "bonds_yields",
        "earnings_cycle",
        "dividends_flow",
        "global_equities_trading",
        "global_risk",
        "ai_platforms",
        "ai_research",
        "global_macro",
        "global_tech_risk",
    }:
        score += 15.0

    if type_confidence >= 0.8:
        score += 10.0
    elif type_confidence >= 0.6:
        score += 6.0

    if len((details or "").strip()) >= 220:
        score += 6.0

    final_score = int(round(min(100.0, max(0.0, score * (0.85 + (0.15 * min(weight, 1.5)))))))
    return final_score


def _metadata_for_item(
    *,
    source: SourceConfig,
    ticker: str | None,
    company_name: str | None,
    headline: str,
    details: str | None,
    announcement_type: str,
    type_confidence: float,
) -> dict[str, object]:
    text = f"{headline} {details or ''}"
    theme = _infer_theme(text=text, source_theme=source.theme)
    impact_score = _kenya_impact_score(
        source=source,
        ticker=ticker,
        company_name=company_name,
        headline=headline,
        details=details,
        announcement_type=announcement_type,
        type_confidence=type_confidence,
        theme=theme,
    )
    threshold = int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD)
    affected_sectors = KENYA_IMPACT_SECTOR_MAP.get(theme or "", [])
    channels = KENYA_IMPACT_CHANNEL_MAP.get(theme or "", [])
    source_scope = source.scope or "kenya_core"
    scope_label = "KENYA CORE"
    if source_scope == "kenya_extended":
        scope_label = "KENYA EXTENDED"
    elif source_scope == "global_outside":
        scope_label = "GLOBAL OUTSIDE"
    return {
        "scope": source_scope,
        "source_scope_label": scope_label,
        "market_region": source.market_region or "kenya",
        "signal_class": source.signal_class or "issuer_disclosure",
        "theme": theme,
        "kenya_impact_score": impact_score,
        "kenya_impact_threshold": threshold,
        "promoted_to_core_feed": bool((source.scope != "global_outside") or (impact_score >= threshold)),
        "affected_sectors": affected_sectors,
        "transmission_channels": channels,
    }


def _is_high_impact_alert(row) -> bool:
    raw = row.raw_payload if isinstance(getattr(row, "raw_payload", None), dict) else {}
    scope = str(raw.get("scope") or "kenya_core")
    impact_score = int(raw.get("kenya_impact_score") or (100 if scope != "global_outside" else 0))
    threshold = int(settings.EMAIL_ALERTS_KENYA_IMPACT_THRESHOLD)
    if scope == "global_outside":
        return impact_score >= threshold

    announcement_type = str(getattr(row, "announcement_type", None) or "other").strip().lower().replace(" ", "_")
    type_ok = announcement_type in {
        "earnings",
        "dividend",
        "board_change",
        "regulator",
        "guidance",
        "rights_issue",
        "merger_acquisition",
        "profit_warning",
        "suspension",
    }
    conf = float(getattr(row, "type_confidence", 0.0) or 0.0)
    conf_ok = conf >= float(settings.ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD)
    severity = str(raw.get("severity") or "").strip().lower()
    severity_ok = severity in {"", "medium", "high", "critical"}
    return bool(type_ok and conf_ok and severity_ok)


def _build_human_summary(
    *,
    rows: list,
    core_successes: int,
    core_failures: int,
    source_failures: int,
    used_validation_fallback: bool = False,
) -> dict:
    if not rows:
        headline = "No new alertable disclosures in this cycle."
        plain_summary = (
            f"Core sources passed: {core_successes}, failed: {core_failures}. "
            f"Total source failures: {source_failures}."
        )
        bullets = [
            "No new disclosures met alert criteria.",
            "System continues monitoring all configured announcement sources.",
        ]
        return {
            "headline": headline,
            "plain_summary": plain_summary,
            "bullets": bullets,
            "counts": {"total": 0, "high": 0, "medium": 0, "low": 0},
            "top_types": [],
            "top_tickers": [],
        }

    by_type: dict[str, int] = {}
    by_ticker: dict[str, int] = {}
    by_severity: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    high_rows: list[str] = []

    for row in rows:
        ann_type = str(getattr(row, "announcement_type", None) or "other").strip().lower() or "other"
        by_type[ann_type] = by_type.get(ann_type, 0) + 1
        ticker = str(getattr(row, "ticker", None) or "UNKNOWN").strip().upper() or "UNKNOWN"
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1

        raw_payload = getattr(row, "raw_payload", None) or {}
        severity = raw_payload.get("severity")
        if severity not in {"high", "medium", "low"}:
            severity, _score = derive_severity(ann_type, float(getattr(row, "type_confidence", 0.0) or 0.0))
        by_severity[str(severity)] = by_severity.get(str(severity), 0) + 1

        if str(severity) == "high":
            headline = str(getattr(row, "headline", "") or "").strip()
            if headline:
                high_rows.append(f"{ticker}: {headline}")

    top_types = sorted(by_type.items(), key=lambda x: x[1], reverse=True)[:3]
    top_tickers = sorted(by_ticker.items(), key=lambda x: x[1], reverse=True)[:3]

    total = len(rows)
    mode_text = "validation snapshot mode" if used_validation_fallback else "new disclosures mode"
    headline = (
        f"{total} disclosure(s) processed in {mode_text}: "
        f"{by_severity.get('high', 0)} high, {by_severity.get('medium', 0)} medium, {by_severity.get('low', 0)} low."
    )
    plain_summary = (
        f"Core sources passed: {core_successes}, failed: {core_failures}. "
        f"Source failures across all tiers: {source_failures}."
    )
    bullets = [
        "Top announcement types: "
        + (", ".join(f"{k} ({v})" for k, v in top_types) if top_types else "none."),
        "Most active tickers: " + (", ".join(f"{k} ({v})" for k, v in top_tickers) if top_tickers else "none."),
        (
            "High-severity watchlist: "
            + ("; ".join(high_rows[:3]) if high_rows else "none in this cycle.")
        ),
    ]

    return {
        "headline": headline,
        "plain_summary": plain_summary,
        "bullets": bullets,
        "counts": {
            "total": total,
            "high": int(by_severity.get("high", 0)),
            "medium": int(by_severity.get("medium", 0)),
            "low": int(by_severity.get("low", 0)),
        },
        "top_types": [{"type": k, "count": int(v)} for k, v in top_types],
        "top_tickers": [{"ticker": k, "count": int(v)} for k, v in top_tickers],
    }


async def run_announcements_pipeline(
    run_id: str | None = None,
    force_send: bool | None = None,
    email_recipients_override: str | None = None,
) -> dict:
    rid = await start_run("announcements", run_id=run_id)
    run_started_at = utc_now()
    force_send_final = bool(force_send) if force_send is not None else False

    metrics: dict = {
        "sources": {},
        "new_alert_count": 0,
        "email_sent": False,
        "email_error": None,
        "alerts_high_impact_sent_count": 0,
        "alerts_suppressed_low_impact_count": 0,
        "llm_calls_count": 0,
        "llm_attempted_count": 0,
        "llm_fallback_failed_count": 0,
        "llm_skipped_budget_count": 0,
        "llm_skipped_breaker_count": 0,
        "llm_breaker_open": False,
        "llm_breaker_reason": None,
        "details_enriched_count": 0,
        "details_failed_count": 0,
        "details_hash_updated_count": 0,
        "details_hash_collision_count": 0,
        "core_sources_passed": [],
        "core_sources_failed": [],
        "secondary_sources_failed": [],
        "alpha_context": {
            "enabled": bool(settings.ANNOUNCEMENTS_ALPHA_ENRICH_ENABLED),
            "requested": 0,
            "received": 0,
            "failed": 0,
            "errors": {},
        },
    }

    total_processed = 0
    total_inserted = 0
    source_failures = 0
    source_successes = 0
    core_failures = 0
    core_successes = 0
    inserted_ids: list[str] = []
    llm_failure_streak = 0
    llm_breaker_open = False
    llm_breaker_reason: str | None = None
    llm_max_calls = max(0, int(settings.ANNOUNCEMENT_LLM_MAX_CALLS_PER_RUN))
    llm_breaker_fail_threshold = max(1, int(settings.ANNOUNCEMENT_LLM_BREAKER_FAIL_THRESHOLD))
    llm_max_concurrency = max(1, int(settings.ANNOUNCEMENT_LLM_MAX_CONCURRENCY))
    llm_budget_remaining = llm_max_calls
    llm_state_lock = asyncio.Lock()
    llm_semaphore = asyncio.Semaphore(llm_max_concurrency)
    known_ids: set[str] = set()
    known_hashes: set[str] = set()

    try:
        await seed_companies()
        source_configs = get_source_configs()
        async with get_session() as session:
            known_ids, known_hashes = await load_known_announcement_keys(session)
            metrics["known_ids_loaded"] = len(known_ids)
            metrics["known_hashes_loaded"] = len(known_hashes)
            async with httpx.AsyncClient(follow_redirects=True) as run_client:
                with bind_http_client(run_client):
                    runnable_sources: list[tuple] = []
                    for source in source_configs:
                        started = time.perf_counter()
                        source_metrics = {
                            "items_found": 0,
                            "items_inserted": 0,
                            "inserted": 0,
                            "duplicates": 0,
                            "duration_ms": 0,
                            "error_type": None,
                            "error": None,
                            "status": "success",
                            "cache_hit": False,
                            "not_modified_count": 0,
                            "rate_limited_count": 0,
                            "breaker_state": "closed",
                            "alpha_enriched": 0,
                        }
                        metrics["sources"][source.source_id] = source_metrics
                        is_core = bool(source.required_for_success or source.tier == "core")

                        now_utc = utc_now()
                        can_run = await source_can_run(
                            session,
                            source_id=source.source_id,
                            breaker_enabled=settings.SOURCE_BREAKER_ENABLED,
                            now_utc=now_utc,
                        )
                        if not can_run:
                            source_metrics["error"] = "source_breaker_open"
                            source_metrics["error_type"] = "source_breaker_open"
                            source_metrics["status"] = "fail"
                            source_metrics["breaker_state"] = "open"
                            source_failures += 1
                            if is_core:
                                core_failures += 1
                                metrics["core_sources_failed"].append(source.source_id)
                            else:
                                metrics["secondary_sources_failed"].append(source.source_id)
                            source_metrics["duration_ms"] = int((time.perf_counter() - started) * 1000)
                            continue

                        runnable_sources.append((source, is_core, started))

                    async def _collect_raw(source):
                        collector = get_collector(source)
                        per_source_budget = max(
                            5,
                            int(source.timeout_secs) * max(1, int(source.retries) + 1) + 5,
                        )
                        hard_cap = max(5, int(settings.ANNOUNCEMENTS_SOURCE_COLLECTION_MAX_SECONDS))
                        timeout_budget = float(min(per_source_budget, hard_cap))
                        try:
                            return await asyncio.wait_for(collector(source), timeout=timeout_budget)
                        except asyncio.TimeoutError as exc:
                            raise SourceFetchError(
                                f"collector timeout after {int(timeout_budget)}s",
                                error_type="timeout",
                            ) from exc

                    fetch_results = await asyncio.gather(
                        *[_collect_raw(source) for source, _is_core, _started in runnable_sources],
                        return_exceptions=True,
                    )

                    for (source, is_core, started), fetch_result in zip(runnable_sources, fetch_results):
                        source_metrics = metrics["sources"][source.source_id]
                        now_utc = utc_now()
                        try:
                            if isinstance(fetch_result, Exception):
                                raise fetch_result
                            raw_items = fetch_result
                            source_metrics["items_found"] = len(raw_items)
                            prepared_rows: list[dict] = []
                            for raw in raw_items[: settings.ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE]:
                                normalized_headline = normalize_headline(raw.headline)
                                if not normalized_headline:
                                    continue

                                canonical_url = canonicalize_url(raw.url, base_url=source.base_url)
                                announcement_date = parse_datetime_to_utc(raw.published_at)
                                date_part = (announcement_date or now_utc).date().isoformat()
                                details = raw.extra.get("details") if isinstance(raw.extra, dict) else None
                                resolver_text = normalized_headline
                                if details:
                                    resolver_text = f"{normalized_headline}\n{str(details)[:800]}"

                                ticker = resolve_ticker(
                                    headline=resolver_text,
                                    ticker_hint=raw.ticker_hint,
                                    company_hint=raw.company_hint,
                                )
                                company_name = resolve_company_name(ticker) or raw.company_hint
                                if ticker is None:
                                    resolver_reason = "unresolved"
                                elif raw.ticker_hint and ticker.upper() == raw.ticker_hint.upper():
                                    resolver_reason = "ticker_hint"
                                elif raw.company_hint:
                                    resolver_reason = "company_hint"
                                else:
                                    resolver_reason = "headline_or_alias"

                                prepared_rows.append(
                                    {
                                        "raw": raw,
                                        "normalized_headline": normalized_headline,
                                        "canonical_url": canonical_url,
                                        "announcement_date": announcement_date,
                                        "date_part": date_part,
                                        "ticker": ticker,
                                        "company_name": company_name,
                                        "resolver_reason": resolver_reason,
                                        "details": details,
                                    }
                                )

                            async def _classify_prepared(prepared: dict):
                                nonlocal llm_breaker_open
                                nonlocal llm_breaker_reason
                                nonlocal llm_failure_streak
                                nonlocal llm_budget_remaining

                                allow_llm = False
                                async with llm_state_lock:
                                    if llm_breaker_open:
                                        metrics["llm_skipped_breaker_count"] += 1
                                    elif llm_budget_remaining <= 0:
                                        metrics["llm_skipped_budget_count"] += 1
                                    else:
                                        allow_llm = True
                                        llm_budget_remaining -= 1

                                if allow_llm:
                                    async with llm_semaphore:
                                        classification = await classify_announcement(
                                            prepared["normalized_headline"],
                                            prepared["details"],
                                            allow_llm=True,
                                        )
                                else:
                                    classification = await classify_announcement(
                                        prepared["normalized_headline"],
                                        prepared["details"],
                                        allow_llm=False,
                                    )

                                async with llm_state_lock:
                                    if classification.llm_attempted:
                                        metrics["llm_attempted_count"] += 1
                                    elif allow_llm:
                                        # Return reserved slot when runtime path did not attempt LLM.
                                        llm_budget_remaining += 1

                                    if classification.llm_used:
                                        metrics["llm_calls_count"] += 1
                                        llm_failure_streak = 0
                                    elif classification.llm_attempted:
                                        metrics["llm_fallback_failed_count"] += 1
                                        llm_error_type = classification.llm_error_type or "unknown_error"
                                        if llm_error_type in {"rate_limited", "auth", "missing_api_key"}:
                                            llm_breaker_open = True
                                            llm_breaker_reason = f"llm_{llm_error_type}"
                                        else:
                                            llm_failure_streak += 1
                                            if llm_failure_streak >= llm_breaker_fail_threshold:
                                                llm_breaker_open = True
                                                llm_breaker_reason = "llm_failure_threshold"

                                return prepared, classification

                            classified_results = await asyncio.gather(
                                *[_classify_prepared(prepared) for prepared in prepared_rows],
                                return_exceptions=True,
                            )

                            normalized_batch: list[NormalizedAnnouncement] = []
                            for classified in classified_results:
                                if isinstance(classified, Exception):
                                    raise classified
                                prepared, classification = classified

                                payload_for_hash = "|".join(
                                    [
                                        prepared["normalized_headline"],
                                        prepared["date_part"],
                                        prepared["canonical_url"],
                                        prepared["details"] or "",
                                    ]
                                )
                                content_hash = make_content_hash(payload_for_hash)
                                announcement_id = make_announcement_id(
                                    source_id=source.source_id,
                                    canonical_url=prepared["canonical_url"],
                                    normalized_headline=prepared["normalized_headline"],
                                    yyyymmdd=prepared["date_part"],
                                )

                                # Fast in-memory dedupe guard before touching DB.
                                if announcement_id in known_ids or content_hash in known_hashes:
                                    total_processed += 1
                                    source_metrics["duplicates"] += 1
                                    continue

                                raw_payload = dict(prepared["raw"].extra or {})
                                raw_payload["resolver_reason"] = prepared["resolver_reason"]
                                raw_payload["llm_used"] = classification.llm_used
                                raw_payload["classification_path"] = classification.classification_path
                                raw_payload["severity"] = classification.severity
                                raw_payload["severity_score"] = classification.severity_score
                                raw_payload.update(
                                    _metadata_for_item(
                                        source=source,
                                        ticker=prepared["ticker"],
                                        company_name=prepared["company_name"],
                                        headline=prepared["normalized_headline"],
                                        details=prepared["details"],
                                        announcement_type=classification.announcement_type,
                                        type_confidence=float(classification.confidence or 0.0),
                                    )
                                )

                                item = NormalizedAnnouncement(
                                    announcement_id=announcement_id,
                                    source_id=source.source_id,
                                    ticker=prepared["ticker"],
                                    company=prepared["company_name"],
                                    headline=prepared["normalized_headline"],
                                    url=prepared["raw"].url,
                                    canonical_url=prepared["canonical_url"],
                                    announcement_date=prepared["announcement_date"],
                                    announcement_type=classification.announcement_type,
                                    type_confidence=classification.confidence,
                                    details=prepared["details"],
                                    content_hash=content_hash,
                                    raw_payload=raw_payload,
                                    classifier_version=CLASSIFIER_VERSION,
                                    normalizer_version=NORMALIZER_VERSION,
                                )
                                normalized_batch.append(item)
                                known_ids.add(item.announcement_id)
                                if item.content_hash:
                                    known_hashes.add(item.content_hash)

                            if settings.ANNOUNCEMENTS_ALPHA_ENRICH_ENABLED and normalized_batch:
                                alpha_tickers = [str(item.ticker).upper() for item in normalized_batch if item.ticker]
                                alpha_rows, alpha_meta = await fetch_alpha_quote_batch(
                                    alpha_tickers,
                                    exchange="NSE",
                                    target_date=now_utc.date(),
                                    max_tickers=int(settings.ANNOUNCEMENTS_ALPHA_MAX_TICKERS_PER_RUN),
                                )
                                alpha_metrics = metrics.get("alpha_context") or {}
                                alpha_metrics["requested"] = int(alpha_metrics.get("requested") or 0) + int(alpha_meta.get("requested") or 0)
                                alpha_metrics["received"] = int(alpha_metrics.get("received") or 0) + int(alpha_meta.get("received") or 0)
                                alpha_metrics["failed"] = int(alpha_metrics.get("failed") or 0) + int(alpha_meta.get("failed") or 0)
                                existing_errors = alpha_metrics.get("errors") or {}
                                if isinstance(existing_errors, dict):
                                    existing_errors.update(alpha_meta.get("errors") or {})
                                    alpha_metrics["errors"] = existing_errors
                                else:
                                    alpha_metrics["errors"] = alpha_meta.get("errors") or {}
                                metrics["alpha_context"] = alpha_metrics

                                for item in normalized_batch:
                                    if not item.ticker:
                                        continue
                                    alpha_ctx = alpha_rows.get(str(item.ticker).upper())
                                    if not alpha_ctx:
                                        continue
                                    raw_payload = dict(item.raw_payload or {})
                                    raw_payload["alpha_context"] = alpha_ctx
                                    item.raw_payload = raw_payload
                                    source_metrics["alpha_enriched"] = int(source_metrics.get("alpha_enriched") or 0) + 1

                            (
                                batch_processed,
                                batch_inserted,
                                batch_duplicates,
                                batch_inserted_ids,
                            ) = await upsert_announcements_batch(session, items=normalized_batch, now_utc=now_utc)

                            total_processed += batch_processed
                            total_inserted += batch_inserted
                            source_metrics["inserted"] += batch_inserted
                            source_metrics["items_inserted"] += batch_inserted
                            source_metrics["duplicates"] += batch_duplicates
                            inserted_ids.extend(batch_inserted_ids)

                            await mark_source_success(session, source_id=source.source_id, metrics=source_metrics, now_utc=now_utc)
                            source_successes += 1
                            if is_core:
                                core_successes += 1
                                metrics["core_sources_passed"].append(source.source_id)

                        except Exception as exc:  # noqa: PERF203
                            source_failures += 1
                            error_type, error_text = classify_source_error(exc)
                            source_metrics["error"] = error_text
                            source_metrics["error_type"] = error_type
                            source_metrics["status"] = "fail"
                            if error_type == "rate_limited":
                                source_metrics["rate_limited_count"] = int(source_metrics.get("rate_limited_count") or 0) + 1
                            if is_core:
                                core_failures += 1
                                metrics["core_sources_failed"].append(source.source_id)
                            else:
                                metrics["secondary_sources_failed"].append(source.source_id)
                            await mark_source_failure(
                                session,
                                source_id=source.source_id,
                                error=error_text,
                                error_type=error_type,
                                now_utc=now_utc,
                                fail_threshold=settings.SOURCE_FAIL_THRESHOLD,
                                cooldown_minutes=settings.SOURCE_COOLDOWN_MINUTES,
                            )
                            logger.exception("source_failed", run_id=rid, source_id=source.source_id, error=error_text)

                        source_metrics["duration_ms"] = int((time.perf_counter() - started) * 1000)
                        await session.commit()

            # alert selection and enrichment pass
            candidates = await list_alert_candidates(
                session,
                run_started_at=run_started_at,
                inserted_ids=inserted_ids,
                limit=max(1, int(settings.ANNOUNCEMENTS_ALERT_CANDIDATE_LIMIT)),
            )
            metrics["alert_candidates_considered"] = len(candidates)
            details_enrich_limit = max(0, int(settings.ANNOUNCEMENTS_DETAILS_ENRICH_LIMIT))
            details_enriched_attempted = 0
            details_skipped_by_limit = 0
            for candidate in candidates:
                if not candidate.details:
                    if details_enriched_attempted >= details_enrich_limit:
                        details_skipped_by_limit += 1
                        continue
                    details_enriched_attempted += 1
                    details = await extract_details(
                        candidate.url,
                        timeout_secs=max(1, int(settings.ANNOUNCEMENTS_DETAILS_ENRICH_TIMEOUT_SECONDS)),
                    )
                    if details:
                        candidate.details = details
                        new_hash = make_content_hash(details + "|" + candidate.canonical_url)
                        hash_conflict = new_hash in known_hashes or await content_hash_exists(
                            session,
                            new_hash,
                            exclude_announcement_id=candidate.announcement_id,
                        )
                        if hash_conflict:
                            metrics["details_hash_collision_count"] += 1
                        else:
                            candidate.content_hash = new_hash
                            known_hashes.add(new_hash)
                            metrics["details_hash_updated_count"] += 1
                        metrics["details_enriched_count"] += 1
                    else:
                        metrics["details_failed_count"] += 1
            metrics["details_enrich_attempted"] = details_enriched_attempted
            metrics["details_skipped_by_limit"] = details_skipped_by_limit

            alert_rows = candidates
            if bool(settings.EMAIL_ALERTS_HIGH_IMPACT_ONLY) and not force_send_final:
                alert_rows = [row for row in candidates if _is_high_impact_alert(row)]
            suppressed = max(0, len(candidates) - len(alert_rows))
            metrics["alerts_suppressed_low_impact_count"] = suppressed
            metrics["new_alert_count"] = len(alert_rows)
            human_summary = _build_human_summary(
                rows=alert_rows,
                core_successes=core_successes,
                core_failures=core_failures,
                source_failures=source_failures,
            )
            human_summary_v2 = from_announcements_summary(summary=human_summary, metrics=metrics)
            metrics["human_summary"] = human_summary
            metrics["human_summary_v2"] = human_summary_v2
            if alert_rows:
                if email_recipients_override:
                    sent, email_error = send_announcements_email(
                        alert_rows,
                        run_id=rid,
                        human_summary=human_summary,
                        human_summary_v2=human_summary_v2,
                        recipients=email_recipients_override,
                    )
                else:
                    sent, email_error = send_announcements_email(
                        alert_rows,
                        run_id=rid,
                        human_summary=human_summary,
                        human_summary_v2=human_summary_v2,
                    )
                metrics["email_sent"] = sent
                metrics["email_error"] = email_error
                metrics["alerts_high_impact_sent_count"] = len(alert_rows) if sent else 0
                if sent:
                    await mark_alerted(
                        session,
                        announcement_ids=[item.announcement_id for item in alert_rows],
                        now_utc=utc_now(),
                    )
                await session.commit()
            elif force_send_final:
                fallback_rows = await list_recent_announcements_for_validation(session, limit=25)
                if fallback_rows:
                    fallback_summary = _build_human_summary(
                        rows=fallback_rows,
                        core_successes=core_successes,
                        core_failures=core_failures,
                        source_failures=source_failures,
                        used_validation_fallback=True,
                    )
                    fallback_summary_v2 = from_announcements_summary(summary=fallback_summary, metrics=metrics)
                    metrics["human_summary"] = fallback_summary
                    metrics["human_summary_v2"] = fallback_summary_v2
                    if email_recipients_override:
                        sent, email_error = send_announcements_email(
                            fallback_rows,
                            run_id=rid,
                            human_summary=fallback_summary,
                            human_summary_v2=fallback_summary_v2,
                            recipients=email_recipients_override,
                        )
                    else:
                        sent, email_error = send_announcements_email(
                            fallback_rows,
                            run_id=rid,
                            human_summary=fallback_summary,
                            human_summary_v2=fallback_summary_v2,
                        )
                    metrics["email_sent"] = sent
                    metrics["email_error"] = email_error
                    metrics["email_validation_fallback"] = True
                    await session.commit()

        metrics["core_sources_passed_count"] = core_successes
        metrics["core_sources_failed_count"] = core_failures
        metrics["llm_breaker_open"] = llm_breaker_open
        metrics["llm_breaker_reason"] = llm_breaker_reason

        status = derive_announcements_status(
            core_failures=core_failures,
            source_failures=source_failures,
            source_successes=source_successes,
            new_alert_count=int(metrics.get("new_alert_count", 0)),
            email_sent=bool(metrics.get("email_sent")),
        )
        if status == "success":
            metrics["status_reason"] = "all_core_sources_passed"
        elif status == "partial":
            metrics["status_reason"] = "core_or_email_degradation"
        else:
            metrics["status_reason"] = "critical_source_or_email_failure"

        await finish_run(
            rid,
            status=status,
            records_processed=total_processed,
            records_new=total_inserted,
            errors_count=source_failures,
            metrics=metrics,
            error_message=metrics.get("email_error") if status != "success" else None,
        )

        logger.info(
            "run_finished",
            run_id=rid,
            agent_name="announcements",
            status=status,
            records_processed=total_processed,
            records_new=total_inserted,
            errors_count=source_failures,
        )

        return {
            "run_id": rid,
            "status": status,
            "records_processed": total_processed,
            "records_new": total_inserted,
            "metrics": metrics,
        }

    except Exception as exc:
        logger.exception("run_failed", run_id=rid, agent_name="announcements", error=str(exc))
        await fail_run(
            rid,
            error_message=str(exc),
            metrics=metrics,
            records_processed=total_processed,
            records_new=total_inserted,
            errors_count=source_failures + 1,
        )
        raise
