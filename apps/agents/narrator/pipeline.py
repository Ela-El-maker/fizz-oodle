from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import json
import random
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.core.config import get_settings
from apps.core.database import get_session
from apps.core.logger import get_logger
from apps.core.models import ContextFetchJob, EvidencePack, InsightCard
from apps.core.run_service import fail_run, finish_run, start_run

settings = get_settings()
logger = get_logger(__name__)

ANNOUNCEMENT_TYPES = {
    "dividend",
    "earnings",
    "regulatory_filing",
    "rights_issue",
    "merger_acquisition",
    "board_change",
    "profit_warning",
    "agm_egm",
    "trading_suspension",
    "other",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _is_cache_valid(card: InsightCard, now_utc: datetime) -> bool:
    if card.expires_at is None:
        return False
    expires = card.expires_at if card.expires_at.tzinfo else card.expires_at.replace(tzinfo=timezone.utc)
    return expires >= now_utc


def _story_cache_requires_refresh(card: InsightCard, *, scope: str, now_utc: datetime) -> bool:
    generated_at = card.generated_at if card.generated_at and card.generated_at.tzinfo else (
        card.generated_at.replace(tzinfo=timezone.utc) if card.generated_at else None
    )
    if generated_at is None:
        return True
    age_minutes = max(0.0, (now_utc - generated_at).total_seconds() / 60.0)
    max_age_minutes = max(5, int(settings.NARRATOR_MARKET_STORY_MAX_AGE_MINUTES))
    degraded_retry_minutes = max(1, int(settings.NARRATOR_DEGRADED_RETRY_MINUTES))

    if age_minutes >= max_age_minutes:
        return scope == "market"
    if (card.fallback_mode or "none") != "none" and age_minutes >= degraded_retry_minutes:
        return True
    if (card.status or "").lower() in {"needs_more_data", "degraded", "failed"} and age_minutes >= degraded_retry_minutes:
        return True
    return False


async def _service_get_json(base: str, path: str, *, params: dict | None = None) -> dict[str, Any]:
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    timeout = max(3, int(settings.NARRATOR_TIMEOUT_SECONDS))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{base.rstrip('/')}{path}",
            params=clean_params,
            headers={"X-API-Key": settings.API_KEY},
        )
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


async def _service_post_json(base: str, path: str, *, params: dict | None = None) -> dict[str, Any]:
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    timeout = max(3, int(settings.NARRATOR_TIMEOUT_SECONDS))
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base.rstrip('/')}{path}",
            params=clean_params,
            headers={"X-API-Key": settings.API_KEY},
        )
    resp.raise_for_status()
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def _split_sentences(text: str, limit: int = 4) -> list[str]:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    out = [p.strip() for p in parts if p.strip()]
    return out[:limit]


def _extract_numeric_facts(text: str, limit: int = 5) -> list[str]:
    if not text:
        return []
    # pick sentences that contain strong numeric signals.
    lines = _split_sentences(text, limit=12)
    picked: list[str] = []
    for line in lines:
        if re.search(r"\b\d+(?:\.\d+)?%\b", line) or re.search(r"\b(?:sh|ksh|kes|usd|eur)\s?\d", line.lower()):
            picked.append(line)
        elif re.search(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b", line):
            picked.append(line)
        if len(picked) >= limit:
            break
    return picked


def _confidence_qualifier(coverage: float) -> str:
    """Return hedging language proportional to evidence coverage."""
    if coverage >= 0.8:
        return "evidence strongly suggests"
    if coverage >= 0.6:
        return "available signals indicate"
    if coverage >= 0.4:
        return "preliminary data suggests"
    return "limited evidence tentatively points to"


def _ticker_sector(ticker: str | None) -> str | None:
    mapping = {
        # Banking
        "ABSA": "Banking", "COOP": "Banking", "KCB": "Banking", "NCBA": "Banking",
        "SBIC": "Banking", "SCBK": "Banking", "DTK": "Banking", "EQTY": "Banking",
        "BKG": "Banking", "HFCK": "Banking", "IMH": "Banking",
        # Consumer / Manufacturing
        "EABL": "Consumer", "BAT": "Consumer", "BOC": "Manufacturing",
        "UNGA": "Consumer", "MSC": "Consumer", "CARB": "Manufacturing",
        "BAMB": "Manufacturing", "ARM": "Manufacturing", "CRWN": "Manufacturing",
        # Insurance
        "JUB": "Insurance", "BRIT": "Insurance", "CIC": "Insurance",
        "KNRE": "Insurance", "LBTY": "Insurance", "SLAM": "Insurance",
        # Media / Telecom
        "NMG": "Media", "SGL": "Media",
        "SCOM": "Telecom",
        # Energy / Utilities
        "KPLC": "Energy", "KEGN": "Energy", "TOTL": "Energy", "UMME": "Energy",
        # Transport / Logistics
        "KQ": "Transport", "PORT": "Transport", "XPRS": "Transport",
        # Investment / Financial Services
        "OCH": "Investment", "CTUM": "Investment", "NSE": "Investment",
        "HAFR": "Investment", "KURV": "Investment",
        # Agriculture
        "EGAD": "Agriculture", "KAPC": "Agriculture", "KUKZ": "Agriculture",
        "LIMT": "Agriculture", "SASN": "Agriculture", "WTK": "Agriculture",
        # Construction / Real Estate
        "DCON": "Construction", "CABL": "Construction",
        # Cross-listed / Regional
        "MTN": "Telecom", "NPN": "Media", "SBK": "Banking",
        "DANGCEM": "Manufacturing", "ZENITHBANK": "Banking",
    }
    if not ticker:
        return None
    return mapping.get(ticker.upper())


def _announcement_research_links(row: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    url = str(row.get("url") or "").strip()
    canonical = str(row.get("canonical_url") or "").strip()
    if url:
        links.append({"label": "Source", "url": url})
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            links.append({"label": "Source Domain", "url": f"{parsed.scheme}://{parsed.netloc}"})
    if canonical and canonical != url:
        links.append({"label": "Canonical", "url": canonical})

    ticker = str(row.get("ticker") or "").strip()
    ann_type = str(row.get("announcement_type") or "other").strip().replace("_", " ")
    if ticker or ann_type:
        q = quote_plus(" ".join([part for part in [ticker, ann_type, "Kenya NSE"] if part]))
        links.append({"label": "Search Related", "url": f"https://www.google.com/search?q={q}"})
    return links


def _normalize_ann_type(raw: Any) -> str:
    value = str(raw or "other").strip().lower()
    return value if value in ANNOUNCEMENT_TYPES else "other"


async def _llm_json(prompt: str, *, max_tokens: int, timeout_seconds: int) -> tuple[dict[str, Any] | None, str | None]:
    mode = (settings.LLM_MODE or "off").lower()
    if mode == "off":
        return None, "llm_disabled"

    attempts = max(1, int(settings.NARRATOR_LLM_RETRY_ATTEMPTS))
    backoff_base = max(0.1, float(settings.NARRATOR_LLM_BACKOFF_BASE_SECONDS))
    connect_timeout = max(2, int(settings.NARRATOR_LLM_CONNECT_TIMEOUT_SECONDS))
    read_timeout = max(connect_timeout, max(timeout_seconds, int(settings.NARRATOR_LLM_READ_TIMEOUT_SECONDS)))
    llm_timeout = httpx.Timeout(connect=connect_timeout, read=read_timeout, write=30.0, pool=10.0)
    llm_limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    last_error: str | None = None
    content = ""

    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=llm_timeout, limits=llm_limits) as client:
                if mode == "api":
                    if not settings.LLM_API_KEY:
                        return None, "missing_api_key"
                    response = await client.post(
                        f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                        json={
                            "model": settings.LLM_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": 0.2,
                            "stream": False,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                elif mode == "local":
                    response = await client.post(
                        f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                        json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                    )
                    response.raise_for_status()
                    content = response.json().get("response", "")
                else:
                    return None, f"unsupported_mode:{mode}"
            break
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.ConnectError as exc:
            lowered = str(exc).lower()
            if "no address associated with hostname" in lowered or "name or service not known" in lowered:
                last_error = "dns_error"
            else:
                last_error = "connect_error"
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                last_error = "rate_limited"
            elif status in {401, 403}:
                return None, "auth"
            elif status >= 500:
                last_error = "upstream_5xx"
            else:
                return None, f"http_{status}"
        except Exception as exc:  # noqa: PERF203
            logger.warning("narrator_llm_error", error=str(exc), attempt=attempt)
            last_error = "unknown_error"

        if attempt >= attempts:
            return None, last_error or "unknown_error"

        sleep_for = (backoff_base * (2 ** (attempt - 1))) + random.uniform(0.05, 0.35)
        await asyncio.sleep(min(4.0, sleep_for))

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed, None
    except Exception:
        pass

    match = re.search(r"\{.*\}", content or "", flags=re.DOTALL)
    if not match:
        return None, "invalid_json"
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed, None
    except Exception:
        return None, "invalid_json"
    return None, "invalid_json"


def _announcement_fallback_sections(row: dict[str, Any], evidence_facts: list[str], *, llm_error: str | None, coverage_score: float = 0.5) -> tuple[dict[str, Any], str]:
    ticker = str(row.get("ticker") or "").strip()
    company = str(row.get("company") or row.get("company_name") or "").strip()
    entity = company or ticker or "the issuer"
    ann_type = _normalize_ann_type(row.get("announcement_type"))
    severity = str(row.get("severity") or "low").strip().lower()
    headline = str(row.get("headline") or "").strip()
    details = str(row.get("details") or "").strip()
    signal_text = f"{headline} {details}".lower()
    qualifier = _confidence_qualifier(coverage_score)

    anchor = evidence_facts[0] if evidence_facts else (headline if headline else f"New {ann_type.replace('_', ' ')} disclosure observed")
    sector = _ticker_sector(ticker)

    def _theme() -> str:
        if any(token in signal_text for token in ("dividend", "payout", "dps", "yield")):
            return "income"
        if any(token in signal_text for token in ("profit", "earnings", "revenue", "results")):
            return "earnings"
        if any(token in signal_text for token in ("board", "director", "governance", "ceo")):
            return "governance"
        if any(token in signal_text for token in ("oil", "fuel", "freight", "port", "shipping", "logistics")):
            return "cost_pressure"
        if any(token in signal_text for token in ("insurance", "takaful")):
            return "insurance"
        if any(token in signal_text for token in ("housing", "property", "mortgage", "real estate")):
            return "housing"
        if any(token in signal_text for token in ("streaming", "showmax", "multichoice", "media")):
            return "media"
        if any(token in signal_text for token in ("private sector", "pmi", "manufacturing", "business activity")):
            return "macro_activity"
        return "general"

    theme = _theme()

    type_watch = {
        "dividend": "payout sustainability, record date, and peer payout reactions",
        "earnings": "margin quality, guidance, and peer earnings read-through",
        "regulatory_filing": "regulatory follow-ups and compliance implications",
        "rights_issue": "subscription appetite, dilution risk, and pricing terms",
        "merger_acquisition": "approval timelines, integration risk, and market concentration",
        "board_change": "strategy continuity and governance signaling",
        "profit_warning": "earnings downgrade magnitude and liquidity implications",
        "agm_egm": "approved resolutions and governance-driven strategic shifts",
        "trading_suspension": "resumption conditions and spillover to related counters",
        "other": "follow-on disclosures and validated primary-source details",
    }

    if theme == "cost_pressure":
        impact_core = "The signal points to potential cost inflation pressure that can squeeze margins in transport-sensitive and import-dependent names."
    elif theme == "income":
        impact_core = "The signal can drive short-term rotation into income-focused counters and reframe yield comparisons across peers."
    elif theme == "earnings":
        impact_core = "The signal can reset near-term valuation expectations as investors compare profitability quality across peers."
    elif theme == "governance":
        impact_core = "The signal can change market expectations around strategy execution and governance risk."
    elif theme == "macro_activity":
        impact_core = "The signal can affect risk appetite across cyclicals if it confirms slower economic momentum."
    elif theme == "media":
        impact_core = "The signal points to competitive repositioning in media/distribution channels with potential spillover to telecom and advertising exposure."
    else:
        impact_core = "The signal may influence positioning as participants absorb follow-on confirmations."

    if severity == "high":
        market_impact = f"{impact_core} This is likely to trigger immediate repricing discussions."
    elif severity == "medium":
        market_impact = f"{impact_core} Market reaction is likely to unfold over the next sessions."
    else:
        market_impact = f"{impact_core} Reaction is likely to be gradual unless confirmed by additional disclosures."

    if sector:
        sector_impact = f"{sector} peers should be monitored for read-through effects from this development."
    elif theme == "cost_pressure":
        sector_impact = "Transport, manufacturing, and consumer sectors are most exposed if higher logistics or energy costs persist."
    elif theme == "housing":
        sector_impact = "Banks, cement/building materials, and real-estate-linked counters may see second-order effects if demand shifts."
    elif theme == "insurance":
        sector_impact = "Insurance and financial-services providers may reprice around product-mix and market-share expectations."
    elif theme == "macro_activity":
        sector_impact = "Broad cyclicals should be monitored for demand sensitivity, while defensives may attract relative flows."
    else:
        sector_impact = "Related sector peers should be monitored to confirm whether this development is isolated or broad."

    watch_items = [
        f"Track {type_watch.get(ann_type, type_watch['other'])}.",
        "Watch subsequent disclosures over the next 24-72 hours.",
        "Validate reaction against price and volume behavior in related names.",
    ]

    if ann_type == "other" and not ticker:
        why_it_matters = (
            "This item is currently unmapped to a tracked ticker and is treated as contextual market intelligence until stronger issuer linkage appears."
        )
    else:
        why_it_matters = (
            f"This is classified as {ann_type.replace('_', ' ')} with {severity} relevance and can shift investor expectations if follow-through confirms the signal."
        )

    if ticker:
        competitor_watch = (
            f"Track competing counters against {ticker} for relative-performance divergence and potential capital rotation."
        )
    elif theme == "cost_pressure":
        competitor_watch = "Track logistics, airline, and import-heavy counters for margin sensitivity versus less exposed peers."
    elif theme == "housing":
        competitor_watch = "Watch listed lenders and property-exposed names for confirmation of demand and affordability trends."
    elif theme == "insurance":
        competitor_watch = "Track insurance and banking names for evidence of product adoption, pricing changes, or share shifts."
    elif theme == "media":
        competitor_watch = "Monitor telecom and media-linked names for partnership changes, subscriber migration, and ad-spend reallocation."
    else:
        competitor_watch = "Track closest peers in the same segment for confirmation or contradiction of this signal."

    sections = {
        "what_happened": f"{entity} published a disclosure — {qualifier} this development: {anchor}",
        "why_it_matters": why_it_matters,
        "market_impact": market_impact,
        "sector_impact": sector_impact,
        "competitor_watch": competitor_watch,
        "what_to_watch_next": watch_items[:5],
    }
    return sections, "evidence_only"


def _validate_announcement_sections(payload: dict[str, Any]) -> dict[str, Any] | None:
    required_text = [
        "what_happened",
        "why_it_matters",
        "market_impact",
        "sector_impact",
        "competitor_watch",
    ]
    out: dict[str, Any] = {}
    for key in required_text:
        value = str(payload.get(key) or "").strip()
        if not value:
            return None
        out[key] = value

    next_raw = payload.get("what_to_watch_next")
    if isinstance(next_raw, list):
        next_items = [str(x).strip() for x in next_raw if str(x).strip()]
    elif isinstance(next_raw, str):
        next_items = [part.strip() for part in re.split(r"[\n;]+", next_raw) if part.strip()]
    else:
        next_items = []

    if len(next_items) < 2:
        return None
    out["what_to_watch_next"] = next_items[:5]
    return out


def _build_announcement_evidence(row: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]], float, float]:
    details = str(row.get("details") or "").strip()
    facts = _extract_numeric_facts(details)
    if not facts:
        facts = _split_sentences(details, limit=3)

    sources: list[dict[str, Any]] = []
    if row.get("url"):
        sources.append({"source_id": row.get("source_id"), "url": row.get("url"), "type": "primary"})
    if row.get("canonical_url") and row.get("canonical_url") != row.get("url"):
        sources.append({"source_id": row.get("source_id"), "url": row.get("canonical_url"), "type": "canonical"})

    evidence_refs = [
        {
            "type": "announcement_source",
            "source_id": str(s.get("source_id") or "unknown"),
            "timestamp": row.get("announcement_date") or row.get("last_seen_at"),
            "url_or_id": s.get("url"),
            "confidence": row.get("type_confidence"),
        }
        for s in sources
    ]

    coverage = 0.35
    if details:
        coverage += 0.25
    if len(facts) >= 2:
        coverage += 0.2
    if row.get("ticker"):
        coverage += 0.1
    if row.get("alpha_context"):
        coverage += 0.1
    coverage = max(0.0, min(1.0, coverage))

    last_seen = _coerce_dt(row.get("last_seen_at"))
    if not last_seen:
        freshness = 0.4
    else:
        age_hours = max(0.0, (_utc_now() - last_seen).total_seconds() / 3600)
        freshness = max(0.0, min(1.0, 1.0 - (age_hours / 72.0)))

    return facts, evidence_refs, coverage, freshness


async def _record_context_job(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: str,
    trigger_type: str,
    status: str,
    attempts: int,
    last_error: str | None,
    started_at: datetime | None,
    finished_at: datetime | None,
    metrics_json: dict[str, Any],
) -> None:
    session.add(
        ContextFetchJob(
            scope_type=scope_type,
            scope_id=scope_id,
            trigger_type=trigger_type,
            status=status,
            attempts=attempts,
            last_error=last_error,
            started_at=started_at,
            finished_at=finished_at,
            metrics_json=metrics_json,
        )
    )


async def _upsert_card(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: str,
    ticker: str | None,
    title: str,
    status: str,
    summary: str,
    sections_json: dict[str, Any],
    quality_json: dict[str, Any],
    llm_used: bool,
    fallback_mode: str,
    error_type: str | None,
    model_name: str | None,
    prompt_version: str,
    generated_at: datetime,
    expires_at: datetime,
) -> InsightCard:
    existing = (
        await session.execute(
            select(InsightCard)
            .where(InsightCard.scope_type == scope_type, InsightCard.scope_id == scope_id)
            .order_by(desc(InsightCard.generated_at))
            .limit(1)
        )
    ).scalars().first()

    if existing is None:
        card = InsightCard(
            scope_type=scope_type,
            scope_id=scope_id,
            ticker=ticker,
            title=title,
            status=status,
            summary=summary,
            sections_json=sections_json,
            quality_json=quality_json,
            llm_used=llm_used,
            fallback_mode=fallback_mode,
            error_type=error_type,
            model_name=model_name,
            prompt_version=prompt_version,
            generated_at=generated_at,
            expires_at=expires_at,
        )
        session.add(card)
        await session.flush()
        return card

    existing.ticker = ticker
    existing.title = title
    existing.status = status
    existing.summary = summary
    existing.sections_json = sections_json
    existing.quality_json = quality_json
    existing.llm_used = llm_used
    existing.fallback_mode = fallback_mode
    existing.error_type = error_type
    existing.model_name = model_name
    existing.prompt_version = prompt_version
    existing.generated_at = generated_at
    existing.expires_at = expires_at
    await session.flush()
    return existing


async def _create_evidence_pack(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: str,
    seed_url: str | None,
    facts: list[str],
    sources: list[dict[str, Any]],
    entity_resolution: dict[str, Any],
    coverage_score: float,
    freshness_score: float,
) -> EvidencePack:
    pack = EvidencePack(
        scope_type=scope_type,
        scope_id=scope_id,
        seed_url=seed_url,
        facts_json={"facts": facts},
        sources_json=sources,
        entity_resolution_json=entity_resolution,
        coverage_score=coverage_score,
        freshness_score=freshness_score,
        created_at=_utc_now(),
    )
    session.add(pack)
    await session.flush()
    return pack


async def _fetch_announcement(announcement_id: str) -> dict[str, Any]:
    return await _service_get_json(settings.AGENT_B_SERVICE_URL, f"/announcements/{announcement_id}")


def _needs_context_refresh(ann_row: dict[str, Any], now_utc: datetime) -> bool:
    min_len = max(80, int(settings.ANNOUNCEMENT_CONTEXT_MIN_DETAILS_CHARS))
    details = str(ann_row.get("details") or "").strip()
    if len(details) < min_len:
        return True

    severity = str(ann_row.get("severity") or "low").strip().lower()
    if severity not in {"high", "medium"}:
        return False

    stale_hours = max(1, int(settings.ANNOUNCEMENT_CONTEXT_STALE_HOURS))
    last_seen = _coerce_dt(ann_row.get("last_seen_at"))
    if last_seen is None:
        return True
    return last_seen < now_utc - timedelta(hours=stale_hours)


async def _refresh_announcement_context(announcement_id: str) -> dict[str, Any]:
    return await _service_post_json(settings.AGENT_B_SERVICE_URL, f"/announcements/{announcement_id}/context/refresh")


def _market_story_fallback(
    *,
    context: str,
    market_date: str,
    prices: list[dict[str, Any]],
    sentiment_rows: list[dict[str, Any]],
    patterns_summary: dict[str, Any],
    announcement_stats: dict[str, Any],
    analyst_context: str | None,
    global_drivers: list[dict[str, Any]],
    llm_error: str | None,
    prev_story: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def _change(open_v: Any, close_v: Any) -> float | None:
        try:
            op = float(open_v)
            cl = float(close_v)
            if op <= 0:
                return None
            return ((cl - op) / op) * 100.0
        except Exception:
            return None

    enriched = []
    for row in prices:
        ch = _change(row.get("open"), row.get("close"))
        if ch is None:
            continue
        enriched.append({"ticker": row.get("ticker"), "change": ch, "volume": float(row.get("volume") or 0)})

    adv = sum(1 for r in enriched if r["change"] > 0)
    dec = sum(1 for r in enriched if r["change"] < 0)
    flat = max(0, len(enriched) - adv - dec)
    avg = (sum(r["change"] for r in enriched) / len(enriched)) if enriched else 0.0

    mood = "mixed"
    if dec >= max(1, int(adv * 1.5)):
        mood = "bearish"
    elif adv >= max(1, int(dec * 1.5)):
        mood = "bullish"

    top_up = sorted([r for r in enriched if r["change"] > 0], key=lambda x: x["change"], reverse=True)[:3]
    top_down = sorted([r for r in enriched if r["change"] < 0], key=lambda x: x["change"])[:3]

    # Build sector aggregation
    sector_data: dict[str, dict] = {}
    for r in enriched:
        sector = _ticker_sector(r.get("ticker")) or "Other"
        if sector not in sector_data:
            sector_data[sector] = {"up": 0, "down": 0, "flat": 0, "total_change": 0.0, "count": 0}
        sd = sector_data[sector]
        sd["count"] += 1
        sd["total_change"] += r["change"]
        if r["change"] > 0:
            sd["up"] += 1
        elif r["change"] < 0:
            sd["down"] += 1
        else:
            sd["flat"] += 1

    # Build sentiment lookup by ticker for cross-signal correlation
    sentiment_by_ticker: dict[str, dict] = {}
    mentions_total = 0
    weighted_bull = 0.0
    weighted_bear = 0.0
    for row in sentiment_rows:
        m = int(row.get("mentions_count") or row.get("mentions") or 0)
        mentions_total += m
        weighted_bull += float(row.get("bullish_pct") or 0.0) * m
        weighted_bear += float(row.get("bearish_pct") or 0.0) * m
        t = str(row.get("ticker") or "").strip().upper()
        if t:
            sentiment_by_ticker[t] = row
    bull = (weighted_bull / mentions_total) if mentions_total else 0.0
    bear = (weighted_bear / mentions_total) if mentions_total else 0.0

    headline = (
        "MARKET STORY – TODAY'S SESSION: Broad selling pressure with selective resilience"
        if mood == "bearish"
        else "MARKET STORY – TODAY'S SESSION: Buyers in control, but still selective"
        if mood == "bullish"
        else "MARKET STORY – TODAY'S SESSION: Mixed tape with selective conviction"
    )

    if not enriched:
        p1 = f"Price data is unavailable for {market_date}. This narrative is running in degraded mode without market activity signals."
    else:
        p1 = (
            f"The market tone for {market_date} is {mood}. Breadth currently shows {adv} advancers versus {dec} decliners, with average move around {avg:.2f}%."
        )

    gainers = ", ".join(
        f"{str(x.get('ticker') or '?')} ({float(x.get('change') or 0.0):+.2f}%)" for x in top_up
    ) or "few pockets"
    laggards = ", ".join(
        f"{str(x.get('ticker') or '?')} ({float(x.get('change') or 0.0):+.2f}%)" for x in top_down
    ) or "laggards"

    # Cross-signal correlation: find divergences between price and sentiment
    divergences: list[str] = []
    for item in top_up[:2] + top_down[:2]:
        t = str(item.get("ticker") or "").upper()
        sr = sentiment_by_ticker.get(t)
        if not sr:
            continue
        bear_pct = float(sr.get("bearish_pct") or 0.0)
        bull_pct = float(sr.get("bullish_pct") or 0.0)
        change = item["change"]
        if change > 0 and bear_pct > 55:
            divergences.append(f"{t} gains {change:+.2f}% despite {bear_pct:.0f}% bearish sentiment")
        elif change < 0 and bull_pct > 55:
            divergences.append(f"{t} declines {change:+.2f}% against {bull_pct:.0f}% bullish sentiment")

    p2 = f"Leadership is narrow: gainers include {gainers} while pressure is concentrated in {laggards}."
    if divergences:
        p2 += f" Signal divergence: {'; '.join(divergences[:2])} — worth monitoring."

    # Sector-level summary
    sector_parts: list[str] = []
    for sec_name, sd in sorted(sector_data.items(), key=lambda kv: kv[1]["count"], reverse=True):
        if sd["count"] >= 2:
            sec_avg = sd["total_change"] / sd["count"]
            sec_mood = "broadly red" if sd["down"] > sd["up"] else "broadly green" if sd["up"] > sd["down"] else "flat"
            sector_parts.append(f"{sec_name} {sec_mood} ({sd['up']}/{sd['count']} advancing, avg {sec_avg:+.2f}%)")
    sector_line = ""
    if sector_parts:
        sector_line = f" Sector view: {'; '.join(sector_parts[:4])}."

    p3 = (
        f"Cross-signal read: sentiment mix is {bull:.1f}% bullish vs {bear:.1f}% bearish across {mentions_total} mentions, "
        f"with {int(patterns_summary.get('active_count') or 0)} active patterns and {int(announcement_stats.get('alerted') or 0)} alerted announcements in the latest cycle."
        f"{sector_line}"
    )
    if global_drivers:
        top = ", ".join(
            f"{str(driver.get('theme') or 'global').replace('_', ' ')} ({int(driver.get('kenya_impact_score') or 0)})"
            for driver in global_drivers[:3]
        )
        # Include transmission mechanism if available
        channels: list[str] = []
        for driver in global_drivers[:2]:
            tc = driver.get("transmission_channels") or []
            asec = driver.get("affected_sectors") or []
            if tc or asec:
                label = str(driver.get("theme") or "global").replace("_", " ")
                parts = []
                if tc:
                    parts.append(f"via {', '.join(str(c) for c in tc[:2])}")
                if asec:
                    parts.append(f"affecting {', '.join(str(s) for s in asec[:2])}")
                channels.append(f"{label} {' '.join(parts)}")
        channel_text = f" Transmission: {'; '.join(channels)}." if channels else ""
        p4 = f"Global outside drivers with Kenya read-through: {top}.{channel_text} Monitor sector transmission before the next local session."
    else:
        p4 = "Global outside lane has no high-impact items crossing the Kenya threshold in this cycle."

    # Temporal delta: compare with previous narrative
    delta_parts: list[str] = []
    if prev_story and isinstance(prev_story, dict):
        prev_quality = prev_story.get("quality") if isinstance(prev_story.get("quality"), dict) else {}
        prev_fallback = str(prev_story.get("fallback_mode") or prev_quality.get("fallback_mode") or "")
        prev_status = str(prev_story.get("status") or "")
        prev_generated = str(prev_story.get("generated_at") or "")
        if prev_fallback and prev_fallback != "none":
            delta_parts.append(f"previous narrative was also in fallback mode ({prev_fallback})")
        if prev_status == "needs_more_data":
            delta_parts.append("prior cycle flagged insufficient data")
        if prev_generated:
            delta_parts.append(f"last generated at {prev_generated[:16]}")
    delta_line = ""
    if delta_parts:
        delta_line = f" Since last narrative: {'; '.join(delta_parts)}."

    p5 = (
        f"This narrative is generated in deterministic fallback mode ({llm_error or 'llm_unavailable'}); "
        f"use linked evidence and incoming updates for confirmation.{delta_line}"
    )
    paragraphs = [p1, p2, p3, p4, p5]
    if analyst_context:
        paragraphs.append(f"Analyst context: {analyst_context.strip()}")

    return {
        "headline": headline,
        "paragraphs": paragraphs[:6],
        "evidence_refs": [
            f"A: {len(enriched)} priced tickers",
            f"Breadth: {adv} up / {dec} down / {flat} flat",
            f"C: {mentions_total} sentiment mentions",
            f"E: {int(patterns_summary.get('active_count') or 0)} active patterns",
        ],
        "global_drivers": global_drivers[:3],
        "fallback_mode": "local_deterministic",
    }


async def get_or_build_announcement_insight(
    session: AsyncSession,
    announcement_id: str,
    *,
    refresh_context_if_needed: bool = True,
    force_regenerate: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now_utc = _utc_now()

    existing = (
        await session.execute(
            select(InsightCard)
            .where(InsightCard.scope_type == "announcement", InsightCard.scope_id == announcement_id)
            .order_by(desc(InsightCard.generated_at))
            .limit(1)
        )
    ).scalars().first()

    if existing and not force_regenerate and _is_cache_valid(existing, now_utc):
        payload = {
            "version": "v1",
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else now_utc.isoformat(),
            "headline": existing.title,
            "classification": (existing.sections_json or {}).get("classification") or {},
            "insight": (existing.sections_json or {}).get("insight") or {},
            "quality": existing.quality_json or {},
            "research_links": (existing.sections_json or {}).get("research_links") or [],
            "evidence_refs": (existing.sections_json or {}).get("evidence_refs") or [],
            "status": existing.status,
            "source": (existing.sections_json or {}).get("source") or {},
        }
        return payload, {"cache_hit": True, "fallback_mode": existing.fallback_mode}

    context_job_started = _utc_now()
    ann = await _fetch_announcement(announcement_id)
    if not ann:
        raise httpx.HTTPStatusError("announcement_not_found", request=None, response=httpx.Response(status_code=404))

    context_refreshed = False
    context_refresh_error: str | None = None
    if refresh_context_if_needed and _needs_context_refresh(ann, now_utc):
        try:
            await _refresh_announcement_context(announcement_id)
            ann = await _fetch_announcement(announcement_id)
            context_refreshed = True
            await _record_context_job(
                session,
                scope_type="announcement",
                scope_id=announcement_id,
                trigger_type="auto_if_needed",
                status="success",
                attempts=1,
                last_error=None,
                started_at=context_job_started,
                finished_at=_utc_now(),
                metrics_json={"reason": "context_missing_or_stale"},
            )
        except Exception as exc:  # noqa: PERF203
            context_refresh_error = str(exc)
            await _record_context_job(
                session,
                scope_type="announcement",
                scope_id=announcement_id,
                trigger_type="auto_if_needed",
                status="partial",
                attempts=1,
                last_error=context_refresh_error,
                started_at=context_job_started,
                finished_at=_utc_now(),
                metrics_json={"reason": "context_refresh_failed"},
            )

    facts, evidence_refs, coverage_score, freshness_score = _build_announcement_evidence(ann)
    evidence_sources = [{"url": ann.get("url"), "source_id": ann.get("source_id")}]
    pack = await _create_evidence_pack(
        session,
        scope_type="announcement",
        scope_id=announcement_id,
        seed_url=ann.get("url"),
        facts=facts,
        sources=evidence_sources,
        entity_resolution={"ticker": ann.get("ticker"), "company": ann.get("company")},
        coverage_score=coverage_score,
        freshness_score=freshness_score,
    )

    ann_type = _normalize_ann_type(ann.get("announcement_type"))
    severity = str(ann.get("severity") or "low").strip().lower()
    confidence = float(ann.get("type_confidence") or 0.5)
    sector = _ticker_sector(str(ann.get("ticker") or "").strip()) or "unknown"

    prompt = (
        "You are Agent F, a market announcement intelligence analyst for NSE-tracked companies. "
        "Do not repeat the headline text verbatim as explanation. "
        "Return JSON only with keys: what_happened, why_it_matters, market_impact, sector_impact, competitor_watch, what_to_watch_next. "
        "what_to_watch_next must be 2-5 short bullets. "
        "Use uncertainty language if evidence is weak. Ground analysis in the numeric facts provided.\n\n"
        f"headline: {ann.get('headline') or ''}\n"
        f"ticker: {ann.get('ticker') or 'unknown'}\n"
        f"company: {ann.get('company') or 'unknown'}\n"
        f"sector: {sector}\n"
        f"announcement_type: {ann_type}\n"
        f"severity: {severity}\n"
        f"confidence: {confidence:.2f}\n"
        f"details: {(ann.get('details') or '')[:1200]}\n"
        f"evidence_facts: {json.dumps(facts, ensure_ascii=True)}\n"
        f"coverage_score: {coverage_score:.2f}\n"
        f"freshness_score: {freshness_score:.2f}\n"
    )

    llm_payload: dict[str, Any] | None = None
    llm_error: str | None = None
    llm_used = False
    fallback_mode = "none"

    if bool(settings.NARRATOR_ENABLED):
        llm_payload, llm_error = await _llm_json(
            prompt,
            max_tokens=max(180, int(settings.NARRATOR_MAX_TOKENS)),
            timeout_seconds=max(3, int(settings.NARRATOR_TIMEOUT_SECONDS)),
        )
        if llm_payload:
            llm_payload = _validate_announcement_sections(llm_payload)
        if llm_payload is None and llm_error in {
            "timeout",
            "dns_error",
            "connect_error",
            "upstream_5xx",
            "rate_limited",
            "unknown_error",
            "invalid_json",
        }:
            retry_prompt = f"{prompt}\nRespond concisely with strict JSON object only."
            llm_payload, llm_error = await _llm_json(
                retry_prompt,
                max_tokens=max(120, int(settings.NARRATOR_MAX_TOKENS) // 2),
                timeout_seconds=max(3, int(settings.NARRATOR_TIMEOUT_SECONDS) - 4),
            )
            if llm_payload:
                llm_payload = _validate_announcement_sections(llm_payload)

    if llm_payload:
        llm_used = True
        sections = llm_payload
    else:
        sections, fallback_mode = _announcement_fallback_sections(ann, facts, llm_error=llm_error, coverage_score=coverage_score)
        if fallback_mode == "none":
            fallback_mode = "evidence_only"

    last_seen = _coerce_dt(ann.get("last_seen_at"))
    context_age_minutes = (
        int(max(0, (now_utc - last_seen).total_seconds() / 60)) if last_seen else None
    )

    status = "ready"
    reason_codes: list[str] = []
    if coverage_score < float(settings.NARRATOR_MIN_COVERAGE_SCORE):
        status = "needs_more_data"
        reason_codes.append("low_coverage")
    if len(evidence_refs) < 2:
        status = "needs_more_data"
        reason_codes.append("insufficient_evidence_refs")
    if context_refresh_error:
        reason_codes.append("context_refresh_failed")
    if llm_error and not llm_used:
        reason_codes.append(f"llm_{llm_error}")

    quality = {
        "llm_used": llm_used,
        "fallback_mode": fallback_mode,
        "context_refreshed": context_refreshed,
        "context_age_minutes": context_age_minutes,
        "coverage_score": round(coverage_score, 3),
        "freshness_score": round(freshness_score, 3),
        "reason_codes": reason_codes,
    }

    summary = sections.get("why_it_matters") or sections.get("what_happened") or "Announcement intelligence generated"
    sections_json = {
        "classification": {
            "announcement_type": ann_type,
            "severity": severity,
            "confidence": round(confidence, 3),
        },
        "insight": sections,
        "research_links": _announcement_research_links(ann),
        "evidence_refs": evidence_refs,
        "source": {
            "id": ann.get("source_id"),
            "url": ann.get("url"),
            "canonical_url": ann.get("canonical_url"),
        },
        "evidence_pack_id": str(pack.pack_id),
    }

    expires_at = now_utc + timedelta(minutes=max(5, int(settings.NARRATOR_CACHE_TTL_MINUTES)))
    card = await _upsert_card(
        session,
        scope_type="announcement",
        scope_id=announcement_id,
        ticker=(str(ann.get("ticker") or "").strip() or None),
        title=str(ann.get("headline") or "(no headline)"),
        status=status,
        summary=summary,
        sections_json=sections_json,
        quality_json=quality,
        llm_used=llm_used,
        fallback_mode=fallback_mode,
        error_type=llm_error,
        model_name=settings.LLM_MODEL if llm_used else None,
        prompt_version="narrator-announcement-v1",
        generated_at=now_utc,
        expires_at=expires_at,
    )

    payload = {
        "version": "v1",
        "generated_at": card.generated_at.isoformat() if card.generated_at else now_utc.isoformat(),
        "headline": card.title,
        "classification": sections_json["classification"],
        "insight": sections,
        "quality": quality,
        "research_links": sections_json["research_links"],
        "evidence_refs": evidence_refs,
        "status": status,
        "source": sections_json["source"],
    }
    meta = {
        "cache_hit": False,
        "llm_used": llm_used,
        "fallback_mode": fallback_mode,
        "context_refreshed": context_refreshed,
        "context_refresh_error": context_refresh_error,
        "reason_codes": reason_codes,
    }
    return payload, meta


async def refresh_announcement_context(session: AsyncSession, announcement_id: str) -> dict[str, Any]:
    started = _utc_now()
    try:
        result = await _refresh_announcement_context(announcement_id)
        await _record_context_job(
            session,
            scope_type="announcement",
            scope_id=announcement_id,
            trigger_type="manual",
            status="success",
            attempts=1,
            last_error=None,
            started_at=started,
            finished_at=_utc_now(),
            metrics_json=result,
        )
        # expire cache by forcing card expiry.
        latest = (
            await session.execute(
                select(InsightCard)
                .where(InsightCard.scope_type == "announcement", InsightCard.scope_id == announcement_id)
                .order_by(desc(InsightCard.generated_at))
                .limit(1)
            )
        ).scalars().first()
        if latest:
            latest.expires_at = _utc_now() - timedelta(seconds=1)
        return result
    except Exception as exc:  # noqa: PERF203
        error = str(exc)
        await _record_context_job(
            session,
            scope_type="announcement",
            scope_id=announcement_id,
            trigger_type="manual",
            status="fail",
            attempts=1,
            last_error=error,
            started_at=started,
            finished_at=_utc_now(),
            metrics_json={},
        )
        raise


async def _build_market_story_payload(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    now_utc = _utc_now()
    market_date = date.today().isoformat()

    # Parallel fetch of all independent data sources
    (
        prices_payload,
        latest_briefing_payload,
        sentiment_payload,
        theme_payload,
        patterns_summary,
        ann_stats,
        global_ann_payload,
        latest_daily,
    ) = await asyncio.gather(
        _service_get_json(settings.AGENT_A_SERVICE_URL, "/prices/daily", params={"date": market_date}),
        _service_get_json(settings.AGENT_A_SERVICE_URL, "/briefings/latest"),
        _service_get_json(settings.AGENT_C_SERVICE_URL, "/sentiment/weekly", params={"limit": 100, "offset": 0}),
        _service_get_json(settings.AGENT_C_SERVICE_URL, "/sentiment/themes/weekly"),
        _service_get_json(settings.AGENT_E_SERVICE_URL, "/patterns/summary"),
        _service_get_json(settings.AGENT_B_SERVICE_URL, "/announcements/stats"),
        _service_get_json(
            settings.AGENT_B_SERVICE_URL,
            "/announcements",
            params={
                "scope": "global_outside",
                "kenya_impact_min": max(0, min(int(settings.GLOBAL_OUTSIDE_KENYA_IMPACT_THRESHOLD), 100)),
                "limit": 12,
            },
        ),
        _service_get_json(settings.AGENT_D_SERVICE_URL, "/reports/latest", params={"type": "daily"}),
    )

    # Fetch previous story for temporal delta tracking
    prev_story: dict[str, Any] = {}
    try:
        prev_payload = await _service_get_json(
            settings.AGENT_F_SERVICE_URL,
            "/stories",
            params={"scope": "market", "limit": 1, "offset": 0},
        )
        prev_items = prev_payload.get("items") if isinstance(prev_payload.get("items"), list) else []
        if prev_items and isinstance(prev_items[0], dict):
            prev_story = prev_items[0]
    except Exception:
        pass

    prices = prices_payload.get("items") if isinstance(prices_payload.get("items"), list) else []
    latest_briefing_item = (
        latest_briefing_payload.get("item") if isinstance(latest_briefing_payload.get("item"), dict) else {}
    )
    briefing_metrics = latest_briefing_item.get("metrics") if isinstance(latest_briefing_item, dict) else {}
    a_global_news_collected = int((briefing_metrics or {}).get("global_news_collected") or 0)
    a_global_themes = (
        (briefing_metrics or {}).get("global_themes")
        if isinstance((briefing_metrics or {}).get("global_themes"), list)
        else []
    )

    if not prices:
        prev_date = (date.today() - timedelta(days=1)).isoformat()
        prev_payload = await _service_get_json(settings.AGENT_A_SERVICE_URL, "/prices/daily", params={"date": prev_date})
        prev_items = prev_payload.get("items") if isinstance(prev_payload.get("items"), list) else []
        if prev_items:
            prices = prev_items
            market_date = prev_date

    sentiment_rows = sentiment_payload.get("items") if isinstance(sentiment_payload.get("items"), list) else []
    theme_rows = theme_payload.get("items") if isinstance(theme_payload.get("items"), list) else []
    global_announcements = global_ann_payload.get("items") if isinstance(global_ann_payload.get("items"), list) else []
    analyst_context = None
    if isinstance(latest_daily.get("item"), dict):
        item = latest_daily["item"]
        hs_v2 = item.get("human_summary_v2") if isinstance(item.get("human_summary_v2"), dict) else {}
        hs = item.get("human_summary") if isinstance(item.get("human_summary"), dict) else {}
        analyst_context = hs_v2.get("plain_summary") or hs.get("plain_summary")

    evidence_refs = [
        f"A: {len(prices)} priced tickers",
        f"A-news: {a_global_news_collected} global+extended headlines",
        f"B: {int(ann_stats.get('alerted') or 0)} alerted announcements",
        f"C: {sum(int(row.get('mentions_count') or row.get('mentions') or 0) for row in sentiment_rows)} sentiment mentions",
        f"E: {int(patterns_summary.get('active_count') or 0)} active patterns",
    ]

    theme_index: dict[str, dict[str, Any]] = {}
    for row in theme_rows:
        if not isinstance(row, dict):
            continue
        theme_key = str(row.get("theme") or "").strip().lower()
        if theme_key:
            theme_index[theme_key] = row

    global_drivers: list[dict[str, Any]] = []
    for row in global_announcements:
        if not isinstance(row, dict):
            continue
        impact_score = int(row.get("kenya_impact_score") or 0)
        theme_key = str(row.get("theme") or "global_macro").strip().lower()
        theme_summary = theme_index.get(theme_key, {})
        global_drivers.append(
            {
                "headline": str(row.get("headline") or "").strip(),
                "theme": theme_key,
                "kenya_impact_score": impact_score,
                "source_id": str(row.get("source_id") or "").strip() or None,
                "signal_class": str(row.get("signal_class") or "").strip() or None,
                "summary": (
                    f"Theme sentiment {theme_key.replace('_', ' ')}: "
                    f"{float(theme_summary.get('weighted_score') or 0.0):+.2f}, "
                    f"mentions {int(theme_summary.get('mentions') or 0)}."
                ),
                "affected_sectors": list(row.get("affected_sectors") or []),
                "transmission_channels": list(row.get("transmission_channels") or []),
            }
        )
    for row in a_global_themes:
        if not isinstance(row, dict):
            continue
        theme_key = str(row.get("theme") or "").strip().lower()
        if not theme_key:
            continue
        global_drivers.append(
            {
                "headline": f"A headlines indicate {theme_key.replace('_', ' ')} activity",
                "theme": theme_key,
                "kenya_impact_score": int(min(100, max(0, (int(row.get("count") or 0) * 10)))),
                "source_id": "agent_a_headline_factor",
                "signal_class": "news_signal",
                "summary": (
                    f"Agent A headline factor: count {int(row.get('count') or 0)}, "
                    f"weighted score {float(row.get('weighted_score') or 0.0):+.2f}."
                ),
                "affected_sectors": [],
                "transmission_channels": [],
            }
        )
    global_drivers.sort(key=lambda item: int(item.get("kenya_impact_score") or 0), reverse=True)
    global_drivers = global_drivers[:3]

    # Build compact price table for LLM grounding
    _price_rows: list[str] = []
    for r in sorted(enriched, key=lambda x: abs(x["change"]), reverse=True)[:12]:
        _price_rows.append(f"{r['ticker']}: {r['change']:+.2f}% vol={int(r.get('volume') or 0)}")
    _price_block = "; ".join(_price_rows) if _price_rows else "none"

    # Compact sentiment snapshot for LLM
    _sent_rows: list[str] = []
    for r in sentiment_rows[:10]:
        t = str(r.get("ticker") or "").strip().upper()
        bp = float(r.get("bullish_pct") or 0)
        brp = float(r.get("bearish_pct") or 0)
        m = int(r.get("mentions_count") or r.get("mentions") or 0)
        _sent_rows.append(f"{t}: bull={bp:.0f}% bear={brp:.0f}% mentions={m}")
    _sent_block = "; ".join(_sent_rows) if _sent_rows else "none"

    # Sector summary for LLM
    _sector_rows: list[str] = []
    for sec_name, sd in sorted(sector_data.items(), key=lambda kv: kv[1]["count"], reverse=True)[:6]:
        if sd["count"] >= 2:
            sa = sd["total_change"] / sd["count"]
            _sector_rows.append(f"{sec_name}: {sd['up']}up/{sd['down']}dn avg={sa:+.2f}%")
    _sector_block = "; ".join(_sector_rows) if _sector_rows else "none"

    prompt = (
        "You are Agent F, market intelligence narrator for the NSE (Nairobi Securities Exchange). "
        "Produce JSON only with keys: headline, paragraphs, evidence_refs. "
        "paragraphs must be 3-6 concise analytical paragraphs grounded in the data below. "
        "Interpret price moves, sentiment, and sector themes — do not dump raw numbers without analysis.\n\n"
        f"market_date: {market_date}\n"
        f"breadth: {adv} advancers, {dec} decliners, {flat} flat, avg_move={avg:+.2f}%\n"
        f"top_movers: {_price_block}\n"
        f"sector_summary: {_sector_block}\n"
        f"sentiment_snapshot: {_sent_block}\n"
        f"active_patterns: {int(patterns_summary.get('active_count') or 0)}\n"
        f"alerted_announcements: {int(ann_stats.get('alerted') or 0)}\n"
        f"global_drivers: {json.dumps(global_drivers, ensure_ascii=True)}\n"
        f"analyst_context: {analyst_context or 'none'}\n"
    )

    llm_used = False
    llm_error = None
    fallback_mode = "none"
    llm_payload, llm_error = await _llm_json(
        prompt,
        max_tokens=max(250, int(settings.NARRATOR_MAX_TOKENS)),
        timeout_seconds=max(3, int(settings.NARRATOR_TIMEOUT_SECONDS)),
    )

    story: dict[str, Any] | None = None
    if isinstance(llm_payload, dict):
        raw_headline = str(llm_payload.get("headline") or "").strip()
        raw_paragraphs = llm_payload.get("paragraphs")
        raw_evidence = llm_payload.get("evidence_refs")
        if raw_headline and isinstance(raw_paragraphs, list):
            paragraphs = [str(p).strip() for p in raw_paragraphs if str(p).strip()]
            if 3 <= len(paragraphs) <= 6:
                evidence = [str(e).strip() for e in (raw_evidence if isinstance(raw_evidence, list) else evidence_refs) if str(e).strip()]
                story = {
                    "headline": raw_headline,
                    "paragraphs": paragraphs,
                    "evidence_refs": evidence[:8],
                    "fallback_mode": "none",
                }
                llm_used = True

    if story is None:
        story = _market_story_fallback(
            context=context,
            market_date=market_date,
            prices=prices,
            sentiment_rows=sentiment_rows,
            patterns_summary=patterns_summary,
            announcement_stats=ann_stats,
            analyst_context=analyst_context,
            global_drivers=global_drivers,
            llm_error=llm_error,
            prev_story=prev_story,
        )
        fallback_mode = story.get("fallback_mode") or "local_deterministic"

    coverage = 0.5
    if prices:
        coverage += 0.2
    if sentiment_rows:
        coverage += 0.1
    if ann_stats:
        coverage += 0.1
    if patterns_summary:
        coverage += 0.1
    coverage = max(0.0, min(1.0, coverage))

    quality = {
        "llm_used": llm_used,
        "fallback_mode": fallback_mode,
        "context_refreshed": False,
        "context_age_minutes": None,
        "coverage_score": round(coverage, 3),
        "freshness_score": 1.0,
        "reason_codes": ([] if llm_used else [f"llm_{llm_error or 'unavailable'}", "local_deterministic_story"]),
    }

    status = "ready" if coverage >= float(settings.NARRATOR_MIN_COVERAGE_SCORE) else "needs_more_data"
    return {
        "scope": "market",
        "context": context,
        "headline": story["headline"],
        "paragraphs": story["paragraphs"],
        "evidence_refs": story["evidence_refs"],
        "quality": quality,
        "status": status,
        "fallback_mode": ("none" if llm_used else (story.get("fallback_mode") or "local_deterministic")),
        "global_drivers": global_drivers,
        "generated_at": now_utc.isoformat(),
    }, {"llm_error": llm_error, "llm_used": llm_used}


async def _build_analyst_story_payload(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    now_utc = _utc_now()
    report_type = context if context in {"daily", "weekly"} else "daily"
    latest = await _service_get_json(settings.AGENT_D_SERVICE_URL, "/reports/latest", params={"type": report_type})
    item = latest.get("item") if isinstance(latest.get("item"), dict) else {}
    hs_v2 = item.get("human_summary_v2") if isinstance(item.get("human_summary_v2"), dict) else {}
    hs = item.get("human_summary") if isinstance(item.get("human_summary"), dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    decision_trace = metrics.get("decision_trace") if isinstance(metrics.get("decision_trace"), list) else []

    base_headline = str(hs_v2.get("headline") or hs.get("headline") or "Analyst Signal Synthesis")
    base_summary = str(hs_v2.get("plain_summary") or hs.get("plain_summary") or "Latest analyst report is available for review.")
    upstream_quality = float((metrics.get("upstream_quality") or {}).get("score") or 0.0) if isinstance(metrics.get("upstream_quality"), dict) else 0.0
    feedback_applied = bool(metrics.get("feedback_applied")) if isinstance(metrics, dict) else False

    top_signals: list[dict[str, Any]] = []
    anomaly_count = 0
    for row in decision_trace[:8]:
        if not isinstance(row, dict):
            continue
        final = row.get("final") if isinstance(row.get("final"), dict) else {}
        anomalies = final.get("anomalies") if isinstance(final.get("anomalies"), list) else []
        anomaly_count += len(anomalies)
        top_signals.append(
            {
                "ticker": row.get("ticker"),
                "direction": final.get("direction"),
                "confidence_pct": final.get("confidence_pct"),
                "strength": final.get("strength"),
                "convergence_score": final.get("convergence_score"),
            }
        )

    evidence_refs = [
        f"D: latest {report_type} report",
        f"D: decision trace rows {len(decision_trace)}",
        f"D: upstream quality {round(upstream_quality, 2)}",
        f"E feedback applied: {'yes' if feedback_applied else 'no'}",
    ]

    prompt = (
        "You are Agent F, writing an analyst explainer for operators. "
        "Return JSON only with keys: headline, paragraphs, evidence_refs. "
        "paragraphs must be 3-5 concise, human-readable paragraphs explaining what the analyst output means. "
        "Avoid generic filler and ground claims in supplied evidence.\n\n"
        f"report_type: {report_type}\n"
        f"headline: {base_headline}\n"
        f"summary: {base_summary}\n"
        f"top_signals: {json.dumps(top_signals, ensure_ascii=True)}\n"
        f"upstream_quality: {round(upstream_quality, 2)}\n"
        f"feedback_applied: {feedback_applied}\n"
        f"anomaly_count: {anomaly_count}\n"
        f"evidence_refs: {json.dumps(evidence_refs, ensure_ascii=True)}\n"
    )

    llm_used = False
    llm_error = None
    llm_payload, llm_error = await _llm_json(
        prompt,
        max_tokens=max(220, int(settings.NARRATOR_MAX_TOKENS)),
        timeout_seconds=max(3, int(settings.NARRATOR_TIMEOUT_SECONDS)),
    )

    headline = base_headline
    paragraphs: list[str] = []
    if isinstance(llm_payload, dict):
        raw_headline = str(llm_payload.get("headline") or "").strip()
        raw_paragraphs = llm_payload.get("paragraphs")
        if raw_headline and isinstance(raw_paragraphs, list):
            cleaned = [str(p).strip() for p in raw_paragraphs if str(p).strip()]
            if 3 <= len(cleaned) <= 5:
                headline = raw_headline
                paragraphs = cleaned
                llm_used = True

    fallback_mode = "none"
    if not llm_used:
        fallback_mode = "local_deterministic"
        signal_bits = []
        for row in top_signals[:3]:
            t = str(row.get("ticker") or "-")
            d = str(row.get("direction") or "neutral")
            c = row.get("confidence_pct")
            signal_bits.append(f"{t} {d} ({c}%)" if c is not None else f"{t} {d}")
        signals_text = ", ".join(signal_bits) if signal_bits else "no dominant ticker signals"
        paragraphs = [
            base_summary,
            f"Top analyst signals currently indicate {signals_text}.",
            (
                f"Upstream quality is {round(upstream_quality, 2)} with "
                f"{'feedback applied' if feedback_applied else 'no archivist feedback applied'}; "
                f"monitor anomaly flags ({anomaly_count}) before escalating conviction."
            ),
        ]

    coverage = 0.2
    if item:
        coverage += 0.4
    if decision_trace:
        coverage += 0.3
    if upstream_quality > 0:
        coverage += 0.1
    coverage = max(0.0, min(1.0, coverage))

    quality = {
        "llm_used": llm_used,
        "fallback_mode": fallback_mode,
        "context_refreshed": False,
        "context_age_minutes": None,
        "coverage_score": round(coverage, 3),
        "freshness_score": 1.0 if item else 0.2,
        "reason_codes": ([] if llm_used else [f"llm_{llm_error or 'unavailable'}", "local_deterministic_story"]),
    }
    status = "ready" if coverage >= float(settings.NARRATOR_MIN_COVERAGE_SCORE) else "needs_more_data"

    return {
        "scope": "analyst",
        "context": report_type,
        "headline": headline,
        "paragraphs": paragraphs,
        "evidence_refs": evidence_refs[:8],
        "quality": quality,
        "status": status,
        "fallback_mode": fallback_mode,
        "generated_at": now_utc.isoformat(),
    }, {"llm_error": llm_error, "llm_used": llm_used}


async def _build_pattern_story_payload(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    now_utc = _utc_now()
    summary = await _service_get_json(settings.AGENT_E_SERVICE_URL, "/patterns/summary")
    patterns_payload = await _service_get_json(settings.AGENT_E_SERVICE_URL, "/patterns", params={"limit": 20})
    items = patterns_payload.get("items") if isinstance(patterns_payload.get("items"), list) else []

    total = int(summary.get("total") or 0)
    active = int(summary.get("active") or 0)
    candidate = int(summary.get("candidate") or 0)
    retired = int(summary.get("retired") or 0)
    confirmed = int(summary.get("confirmed") or 0)

    top_items: list[dict[str, Any]] = []
    for row in items[:6]:
        if not isinstance(row, dict):
            continue
        top_items.append(
            {
                "ticker": row.get("ticker"),
                "pattern_type": row.get("pattern_type"),
                "status": row.get("status"),
                "confidence_pct": row.get("confidence_pct"),
                "accuracy_pct": row.get("accuracy_pct"),
                "occurrence_count": row.get("occurrence_count"),
                "avg_impact_1d": row.get("avg_impact_1d"),
            }
        )

    evidence_refs = [
        f"E: total patterns {total}",
        f"E: active {active}, candidate {candidate}, retired {retired}, confirmed {confirmed}",
        f"E: top rows analyzed {len(top_items)}",
    ]

    prompt = (
        "You are Agent F, writing a pattern explainer for operators. "
        "Return JSON only with keys: headline, paragraphs, evidence_refs. "
        "paragraphs must be 3-5 concise, human-readable paragraphs. "
        "Explain what pattern status mix implies for signal reliability and what to watch next.\n\n"
        f"context: {context}\n"
        f"summary: {json.dumps({'total': total, 'active': active, 'candidate': candidate, 'retired': retired, 'confirmed': confirmed}, ensure_ascii=True)}\n"
        f"top_patterns: {json.dumps(top_items, ensure_ascii=True)}\n"
        f"evidence_refs: {json.dumps(evidence_refs, ensure_ascii=True)}\n"
    )

    llm_used = False
    llm_error = None
    llm_payload, llm_error = await _llm_json(
        prompt,
        max_tokens=max(220, int(settings.NARRATOR_MAX_TOKENS)),
        timeout_seconds=max(3, int(settings.NARRATOR_TIMEOUT_SECONDS)),
    )

    headline = "Pattern Explainer"
    paragraphs: list[str] = []
    if isinstance(llm_payload, dict):
        raw_headline = str(llm_payload.get("headline") or "").strip()
        raw_paragraphs = llm_payload.get("paragraphs")
        if raw_headline and isinstance(raw_paragraphs, list):
            cleaned = [str(p).strip() for p in raw_paragraphs if str(p).strip()]
            if 3 <= len(cleaned) <= 5:
                headline = raw_headline
                paragraphs = cleaned
                llm_used = True

    fallback_mode = "none"
    if not llm_used:
        fallback_mode = "local_deterministic"
        lead = top_items[0] if top_items else {}
        lead_ticker = str(lead.get("ticker") or "N/A")
        lead_status = str(lead.get("status") or "unknown")
        lead_conf = lead.get("confidence_pct")
        lead_conf_text = f"{lead_conf}%" if lead_conf is not None else "n/a"
        paragraphs = [
            f"Current pattern memory tracks {total} patterns: {active} active, {candidate} candidates, {retired} retired, and {confirmed} confirmed.",
            f"Lead pattern currently is {lead_ticker} ({lead_status}, confidence {lead_conf_text}), which indicates where historical signal monitoring is currently focused.",
            "Use active and candidate patterns for watchlist prioritization, while retired patterns should not drive conviction without fresh confirmation.",
        ]

    coverage = 0.3
    if total > 0:
        coverage += 0.4
    if top_items:
        coverage += 0.3
    coverage = max(0.0, min(1.0, coverage))

    quality = {
        "llm_used": llm_used,
        "fallback_mode": fallback_mode,
        "context_refreshed": False,
        "context_age_minutes": None,
        "coverage_score": round(coverage, 3),
        "freshness_score": 1.0 if total > 0 else 0.2,
        "reason_codes": ([] if llm_used else [f"llm_{llm_error or 'unavailable'}", "local_deterministic_story"]),
    }
    status = "ready" if coverage >= float(settings.NARRATOR_MIN_COVERAGE_SCORE) else "needs_more_data"

    return {
        "scope": "pattern",
        "context": context,
        "headline": headline,
        "paragraphs": paragraphs,
        "evidence_refs": evidence_refs[:8],
        "quality": quality,
        "status": status,
        "fallback_mode": fallback_mode,
        "generated_at": now_utc.isoformat(),
    }, {"llm_error": llm_error, "llm_used": llm_used}


async def get_or_build_story(
    session: AsyncSession,
    *,
    scope: str,
    context: str,
    ticker: str | None = None,
    force_regenerate: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now_utc = _utc_now()
    scope_type = scope
    scope_id = f"{context}:{ticker or 'all'}"

    existing = (
        await session.execute(
            select(InsightCard)
            .where(InsightCard.scope_type == scope_type, InsightCard.scope_id == scope_id)
            .order_by(desc(InsightCard.generated_at))
            .limit(1)
        )
    ).scalars().first()
    if (
        existing
        and not force_regenerate
        and _is_cache_valid(existing, now_utc)
        and not _story_cache_requires_refresh(existing, scope=scope, now_utc=now_utc)
    ):
        sections = existing.sections_json or {}
        payload = {
            "card_id": str(existing.card_id),
            "scope": scope,
            "context": context,
            "ticker": existing.ticker,
            "title": existing.title,
            "headline": sections.get("headline") or existing.title,
            "paragraphs": sections.get("paragraphs") or [],
            "evidence_refs": sections.get("evidence_refs") or [],
            "global_drivers": sections.get("global_drivers") or [],
            "quality": existing.quality_json or {},
            "status": existing.status,
            "fallback_mode": existing.fallback_mode,
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else now_utc.isoformat(),
        }
        return payload, {"cache_hit": True}

    if scope == "market":
        built, meta = await _build_market_story_payload(context)
        headline = str(built.get("headline") or "Market story")
        sections_json = {
            "headline": headline,
            "paragraphs": built.get("paragraphs") or [],
            "evidence_refs": built.get("evidence_refs") or [],
            "global_drivers": built.get("global_drivers") or [],
        }
        quality = built.get("quality") if isinstance(built.get("quality"), dict) else {}
        llm_used = bool(quality.get("llm_used"))
        fallback_mode = str(built.get("fallback_mode") or "none")
        error_type = None
        if isinstance(meta, dict):
            error_type = meta.get("llm_error")
    elif scope == "analyst":
        built, meta = await _build_analyst_story_payload(context)
        headline = str(built.get("headline") or "Analyst Explanation")
        sections_json = {
            "headline": headline,
            "paragraphs": built.get("paragraphs") or [],
            "evidence_refs": built.get("evidence_refs") or ["D: latest analyst report"],
        }
        quality = built.get("quality") if isinstance(built.get("quality"), dict) else {}
        llm_used = bool(quality.get("llm_used"))
        fallback_mode = str(built.get("fallback_mode") or "none")
        error_type = None
        if isinstance(meta, dict):
            error_type = meta.get("llm_error")
    elif scope == "pattern":
        built, meta = await _build_pattern_story_payload(context)
        headline = str(built.get("headline") or "Pattern Explainer")
        sections_json = {
            "headline": headline,
            "paragraphs": built.get("paragraphs") or [],
            "evidence_refs": built.get("evidence_refs") or ["E: patterns summary"],
        }
        quality = built.get("quality") if isinstance(built.get("quality"), dict) else {}
        llm_used = bool(quality.get("llm_used"))
        fallback_mode = str(built.get("fallback_mode") or "none")
        error_type = None
        if isinstance(meta, dict):
            error_type = meta.get("llm_error")
    elif scope == "announcement":
        # announcement feed-level summary
        stats = await _service_get_json(settings.AGENT_B_SERVICE_URL, "/announcements/stats")
        total = int(stats.get("total") or 0)
        alerted = int(stats.get("alerted") or 0)
        unalerted = int(stats.get("unalerted") or 0)
        headline = "Announcement Intelligence Feed"
        sections_json = {
            "headline": headline,
            "paragraphs": [
                f"The feed is currently tracking {total} disclosures, with {alerted} already alerted and {unalerted} awaiting workflow actions.",
                "Prioritize high-severity items and verify follow-up disclosures for names with rapid updates.",
            ],
            "evidence_refs": ["B: announcement stats"],
        }
        quality = {
            "llm_used": False,
            "fallback_mode": "evidence_only",
            "coverage_score": 0.9 if total > 0 else 0.2,
            "freshness_score": 1.0,
            "reason_codes": [] if total > 0 else ["no_announcements"],
        }
        llm_used = False
        fallback_mode = "evidence_only"
        error_type = None
    else:
        raise ValueError(f"Unsupported story scope: {scope}")

    status = "ready" if float(quality.get("coverage_score") or 0) >= float(settings.NARRATOR_MIN_COVERAGE_SCORE) else "needs_more_data"
    expires_at = now_utc + timedelta(minutes=max(5, int(settings.NARRATOR_CACHE_TTL_MINUTES)))

    card = await _upsert_card(
        session,
        scope_type=scope_type,
        scope_id=scope_id,
        ticker=ticker,
        title=headline,
        status=status,
        summary=(sections_json.get("paragraphs") or [""])[0],
        sections_json=sections_json,
        quality_json=quality,
        llm_used=llm_used,
        fallback_mode=fallback_mode,
        error_type=error_type,
        model_name=settings.LLM_MODEL if llm_used else None,
        prompt_version=f"narrator-{scope}-v1",
        generated_at=now_utc,
        expires_at=expires_at,
    )

    payload = {
        "card_id": str(card.card_id),
        "scope": scope,
        "context": context,
        "ticker": ticker,
        "title": card.title,
        "headline": sections_json.get("headline") or card.title,
        "paragraphs": sections_json.get("paragraphs") or [],
        "evidence_refs": sections_json.get("evidence_refs") or [],
        "global_drivers": sections_json.get("global_drivers") or [],
        "quality": quality,
        "status": status,
        "fallback_mode": fallback_mode,
        "generated_at": card.generated_at.isoformat() if card.generated_at else now_utc.isoformat(),
    }
    return payload, {"cache_hit": False}


async def list_stories(
    session: AsyncSession,
    *,
    scope: str | None,
    ticker: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    stmt = select(InsightCard).order_by(desc(InsightCard.generated_at)).limit(safe_limit).offset(safe_offset)
    if scope:
        stmt = stmt.where(InsightCard.scope_type == scope)
    if ticker:
        stmt = stmt.where(InsightCard.ticker == ticker)
    if status:
        stmt = stmt.where(InsightCard.status == status)

    rows = (await session.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        sections = row.sections_json or {}
        items.append(
            {
                "card_id": str(row.card_id),
                "scope": row.scope_type,
                "scope_id": row.scope_id,
                "ticker": row.ticker,
                "title": row.title,
                "headline": sections.get("headline") or row.title,
                "paragraphs": sections.get("paragraphs") or [],
                "evidence_refs": sections.get("evidence_refs") or [],
                "global_drivers": sections.get("global_drivers") or [],
                "quality": row.quality_json or {},
                "status": row.status,
                "fallback_mode": row.fallback_mode,
                "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            }
        )
    return items


async def get_story_by_card_id(session: AsyncSession, card_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(select(InsightCard).where(InsightCard.card_id == card_id).limit(1))
    ).scalars().first()
    if row is None:
        return None
    sections = row.sections_json or {}
    return {
        "card_id": str(row.card_id),
        "scope": row.scope_type,
        "scope_id": row.scope_id,
        "ticker": row.ticker,
        "title": row.title,
        "headline": sections.get("headline") or row.title,
        "paragraphs": sections.get("paragraphs") or [],
        "evidence_refs": sections.get("evidence_refs") or [],
        "global_drivers": sections.get("global_drivers") or [],
        "quality": row.quality_json or {},
        "status": row.status,
        "fallback_mode": row.fallback_mode,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


async def run_narrator_pipeline(run_id: str | None = None, *, force_regenerate: bool | None = None) -> dict[str, Any]:
    rid = run_id or await start_run("narrator")
    force = bool(force_regenerate)

    metrics: dict[str, Any] = {
        "stories_built": 0,
        "announcement_insights_built": 0,
        "errors": [],
    }

    try:
        async with get_session() as session:
            for scope, context in (("market", "prices"), ("analyst", "daily"), ("pattern", "summary"), ("announcement", "feed")):
                try:
                    await get_or_build_story(session, scope=scope, context=context, force_regenerate=force)
                    metrics["stories_built"] = int(metrics.get("stories_built") or 0) + 1
                except Exception as exc:  # noqa: PERF203
                    metrics["errors"].append({"scope": scope, "error": str(exc)})

            try:
                ann_list = await _service_get_json(settings.AGENT_B_SERVICE_URL, "/announcements", params={"limit": 15, "offset": 0})
                for item in ann_list.get("items", [])[:15]:
                    announcement_id = item.get("announcement_id")
                    if not announcement_id:
                        continue
                    try:
                        await get_or_build_announcement_insight(
                            session,
                            str(announcement_id),
                            refresh_context_if_needed=True,
                            force_regenerate=force,
                        )
                        metrics["announcement_insights_built"] = int(metrics.get("announcement_insights_built") or 0) + 1
                    except Exception as exc:  # noqa: PERF203
                        metrics["errors"].append({"announcement_id": announcement_id, "error": str(exc)})
            except Exception as exc:  # noqa: PERF203
                metrics["errors"].append({"scope": "announcement_seed", "error": str(exc)})

            await session.commit()

        status = "success" if not metrics["errors"] else "partial"
        metrics["status_reason"] = "narrator_completed" if status == "success" else "narrator_partial_errors"
        await finish_run(
            rid,
            status=status,
            metrics=metrics,
            records_processed=int(metrics.get("stories_built") or 0) + int(metrics.get("announcement_insights_built") or 0),
            records_new=int(metrics.get("announcement_insights_built") or 0),
            errors_count=len(metrics["errors"]),
            error_message=None if status == "success" else "narrator_partial_errors",
        )
        return {"run_id": rid, "status": status, "metrics": metrics}
    except Exception as exc:
        metrics["status_reason"] = "narrator_failed"
        await fail_run(
            rid,
            error_message=str(exc),
            metrics=metrics,
            records_processed=0,
            records_new=0,
            errors_count=max(1, len(metrics.get("errors") or [])),
        )
        raise
