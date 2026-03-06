from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from apps.agents.announcements.enrich import extract_details
from apps.agents.announcements.hashing import make_content_hash
from apps.agents.announcements.severity import derive_severity
from apps.core.config import get_settings
from apps.core.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)

_JSON_PATTERN = re.compile(r"\{.*\}", flags=re.DOTALL)
_SUPPORTED_TYPES = {
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


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _severity_for_row(row: Any) -> tuple[str, float]:
    raw_payload = getattr(row, "raw_payload", None) or {}
    severity = raw_payload.get("severity")
    if isinstance(severity, str) and severity.strip():
        score = raw_payload.get("severity_score")
        try:
            return severity.lower().strip(), float(score) if score is not None else 0.5
        except (TypeError, ValueError):
            return severity.lower().strip(), 0.5
    derived, score = derive_severity(getattr(row, "announcement_type", "other"), float(getattr(row, "type_confidence", 0.5) or 0.5))
    return derived, float(score)


def _cache_is_valid(cached: dict[str, Any], now_utc: datetime) -> bool:
    if (cached.get("version") or "").strip() != "v1":
        return False
    generated_at = cached.get("generated_at")
    if not isinstance(generated_at, str):
        return False
    try:
        generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except Exception:
        return False
    generated_dt = _to_utc(generated_dt)
    if generated_dt is None:
        return False
    ttl_minutes = max(1, int(settings.ANNOUNCEMENT_INSIGHT_CACHE_TTL_MINUTES))
    return generated_dt >= now_utc - timedelta(minutes=ttl_minutes)


def _needs_context_refresh(row: Any, now_utc: datetime) -> bool:
    details = (getattr(row, "details", None) or "").strip()
    min_chars = max(80, int(settings.ANNOUNCEMENT_CONTEXT_MIN_DETAILS_CHARS))
    if len(details) < min_chars:
        return True
    severity, _ = _severity_for_row(row)
    if severity not in {"high", "medium"}:
        return False
    stale_hours = max(1, int(settings.ANNOUNCEMENT_CONTEXT_STALE_HOURS))
    last_seen_at = _to_utc(getattr(row, "last_seen_at", None))
    if last_seen_at is None:
        return True
    return last_seen_at < now_utc - timedelta(hours=stale_hours)


def _safe_json_obj(content: str) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = _JSON_PATTERN.search(content)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _coerce_watch_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out = [str(v).strip() for v in value if str(v).strip()]
        return out[:5]
    if isinstance(value, str) and value.strip():
        parts = [p.strip() for p in re.split(r"[;\n]+", value) if p.strip()]
        return parts[:5]
    return []


def _research_links(row: Any) -> list[dict[str, str]]:
    url = str(getattr(row, "url", "") or "").strip()
    canonical_url = str(getattr(row, "canonical_url", "") or "").strip()
    links: list[dict[str, str]] = []
    if url:
        links.append({"label": "Source", "url": url})
        parsed = urlparse(url)
        domain_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        if domain_url:
            links.append({"label": "Source Domain", "url": domain_url})
    if canonical_url and canonical_url != url:
        links.append({"label": "Canonical", "url": canonical_url})

    ticker = str(getattr(row, "ticker", "") or "").strip()
    ann_type = str(getattr(row, "announcement_type", "") or "").strip().replace("_", " ")
    if ticker or ann_type:
        q = quote_plus(" ".join(part for part in [ticker, ann_type, "Kenya NSE"] if part))
        links.append({"label": "Search Related", "url": f"https://www.google.com/search?q={q}"})
    return links


def _fallback_insight(row: Any, now_utc: datetime, *, llm_used: bool, context_refreshed: bool, context_age_minutes: int | None, llm_error: str | None = None) -> dict[str, Any]:
    announcement_type = str(getattr(row, "announcement_type", "other") or "other").strip().lower()
    if announcement_type not in _SUPPORTED_TYPES:
        announcement_type = "other"
    severity, severity_score = _severity_for_row(row)
    ticker = str(getattr(row, "ticker", "") or "").strip()
    company = str(getattr(row, "company_name", "") or "").strip()
    type_confidence = float(getattr(row, "type_confidence", 0.5) or 0.5)
    headline = str(getattr(row, "headline", "") or "").strip()
    details = str(getattr(row, "details", "") or "").strip()

    type_to_watch = {
        "dividend": "dividend declaration date, payout sustainability, and peer payout responses",
        "earnings": "margin quality, forward guidance, and whether peers report similar trends",
        "regulatory_filing": "regulator follow-ups, compliance deadlines, and legal implications",
        "rights_issue": "capital raise pricing, dilution risk, and subscription demand",
        "merger_acquisition": "deal terms, approvals, integration risk, and competitor response",
        "board_change": "strategy continuity, governance signals, and investor confidence",
        "profit_warning": "earnings revision magnitude, management explanation, and liquidity pressure",
        "agm_egm": "shareholder resolutions, policy shifts, and governance votes",
        "trading_suspension": "suspension reason, reopening criteria, and spillover risk",
        "other": "new disclosures, confirmation from official filings, and cross-market reaction",
    }
    signal_impact = {
        "high": "could produce a sharp near-term repricing",
        "medium": "is likely to influence positioning over the next sessions",
        "low": "is likely to be digested gradually unless new information emerges",
    }

    entity = company or ticker or "the issuer"
    why = (
        f"This appears as a {announcement_type.replace('_', ' ')} disclosure and carries {severity} operational relevance."
        if announcement_type != "other"
        else "This disclosure introduces potentially material information that still needs further confirmation context."
    )
    happened = (
        f"The announcement indicates that {entity} published a new market disclosure."
        if not details
        else f"The disclosure from {entity} adds operational detail that may affect expected performance and investor positioning."
    )

    if ticker:
        competitor_watch = f"Track peer counters against {ticker} for relative performance divergence and capital rotation."
    else:
        competitor_watch = "Track peer issuers in the same segment for confirmation or contradiction of this signal."

    what_next = _coerce_watch_list(
        [
            f"Monitor {type_to_watch.get(announcement_type, type_to_watch['other'])}.",
            "Watch follow-up disclosures in the next 24-72 hours.",
            "Validate reaction against volume and price movement in related counters.",
        ]
    )
    if llm_error:
        what_next.append(f"Note: narrative generated in fallback mode ({llm_error}).")

    return {
        "version": "v1",
        "generated_at": now_utc.isoformat(),
        "source": {
            "id": getattr(row, "source_id", None),
            "url": getattr(row, "url", None),
            "canonical_url": getattr(row, "canonical_url", None),
        },
        "headline": headline,
        "classification": {
            "announcement_type": announcement_type,
            "severity": severity,
            "confidence": round(max(type_confidence, severity_score), 3),
        },
        "insight": {
            "what_happened": happened,
            "why_it_matters": why,
            "market_impact": f"For investors, this {signal_impact.get(severity, signal_impact['medium'])}.",
            "sector_impact": "Expect related sector names to reprice based on whether this signal is read as growth, risk, or neutral flow.",
            "competitor_watch": competitor_watch,
            "what_to_watch_next": what_next[:5],
        },
        "quality": {
            "llm_used": llm_used,
            "fallback_used": True,
            "context_refreshed": context_refreshed,
            "context_age_minutes": context_age_minutes,
            "llm_error": llm_error,
        },
        "research_links": _research_links(row),
    }


def _validate_llm_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    required = [
        "what_happened",
        "why_it_matters",
        "market_impact",
        "sector_impact",
        "competitor_watch",
        "what_to_watch_next",
    ]
    for key in required:
        if key not in payload:
            return None

    out: dict[str, Any] = {}
    for key in required[:-1]:
        value = payload.get(key)
        text = str(value).strip() if value is not None else ""
        if not text:
            return None
        out[key] = text

    next_watch = _coerce_watch_list(payload.get("what_to_watch_next"))
    if not next_watch:
        return None
    out["what_to_watch_next"] = next_watch
    return out


async def _llm_generate_sections(row: Any) -> tuple[dict[str, Any] | None, str | None]:
    mode = (settings.LLM_MODE or "off").lower()
    if mode == "off":
        return None, "llm_disabled"
    if mode not in {"api", "local"}:
        return None, f"invalid_mode:{mode}"

    severity, _ = _severity_for_row(row)
    announcement_type = str(getattr(row, "announcement_type", "other") or "other").strip().lower()
    if announcement_type not in _SUPPORTED_TYPES:
        announcement_type = "other"
    headline = str(getattr(row, "headline", "") or "").strip()
    details = str(getattr(row, "details", "") or "").strip()
    ticker = str(getattr(row, "ticker", "") or "").strip()
    company = str(getattr(row, "company_name", "") or "").strip()
    source_id = str(getattr(row, "source_id", "") or "").strip()
    alpha_context = getattr(row, "raw_payload", None) or {}
    alpha_ctx = alpha_context.get("alpha_context") if isinstance(alpha_context, dict) else None

    prompt = (
        "You are an announcement intelligence analyst. "
        "Do not repeat the headline text in your explanations. "
        "Write concise, professional market analysis. "
        "Return JSON only with keys: "
        "what_happened, why_it_matters, market_impact, sector_impact, competitor_watch, what_to_watch_next. "
        "what_to_watch_next must be a list of 2-4 short bullets. "
        "If evidence is weak, explicitly mention uncertainty.\n\n"
        f"ticker: {ticker or 'unknown'}\n"
        f"company: {company or 'unknown'}\n"
        f"type: {announcement_type}\n"
        f"severity: {severity}\n"
        f"source_id: {source_id or 'unknown'}\n"
        f"headline: {headline}\n"
        f"details: {details[:1200]}\n"
        f"alpha_context: {json.dumps(alpha_ctx, default=str) if alpha_ctx else '{}'}\n"
    )

    timeout_seconds = max(2, int(settings.ANNOUNCEMENT_INSIGHT_TIMEOUT_SECONDS))
    max_tokens = max(120, int(settings.ANNOUNCEMENT_INSIGHT_MAX_TOKENS))
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
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
            else:
                response = await client.post(
                    f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                    json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                content = response.json().get("response", "")
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 429:
            return None, "rate_limited"
        if code in {401, 403}:
            return None, "auth"
        if code >= 500:
            return None, "upstream_5xx"
        return None, f"http_{code}"
    except Exception as exc:
        logger.warning("announcement_insight_llm_failed", error=str(exc))
        return None, "unknown_error"

    parsed = _safe_json_obj(content if isinstance(content, str) else "")
    if not parsed:
        return None, "invalid_json"
    validated = _validate_llm_payload(parsed)
    if not validated:
        return None, "schema_invalid"
    return validated, None


async def refresh_announcement_context(row: Any, now_utc: datetime) -> dict[str, Any]:
    url = str(getattr(row, "url", "") or "").strip()
    if not url:
        return {"refreshed": False, "updated": False, "reason": "missing_url"}
    try:
        details = await extract_details(url)
    except Exception as exc:
        return {"refreshed": False, "updated": False, "reason": f"extract_error:{exc}"}
    if not details:
        return {"refreshed": False, "updated": False, "reason": "no_details_extracted"}

    updated = False
    if (getattr(row, "details", None) or "").strip() != details.strip():
        row.details = details
        updated = True
    canonical_url = str(getattr(row, "canonical_url", "") or "").strip() or url
    new_hash = make_content_hash(details + "|" + canonical_url)
    if getattr(row, "content_hash", None) != new_hash:
        row.content_hash = new_hash
        updated = True
    raw_payload = dict(getattr(row, "raw_payload", None) or {})
    if "insight_v1" in raw_payload:
        raw_payload.pop("insight_v1", None)
        row.raw_payload = raw_payload
        updated = True
    row.last_seen_at = now_utc
    return {
        "refreshed": True,
        "updated": updated,
        "details_length": len(details),
        "reason": "ok",
    }


async def get_or_build_announcement_insight(
    row: Any,
    *,
    refresh_context_if_needed: bool,
    force_regenerate: bool,
    now_utc: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now_utc = _to_utc(now_utc) or datetime.now(timezone.utc)
    raw_payload = dict(getattr(row, "raw_payload", None) or {})
    cached = raw_payload.get("insight_v1") if isinstance(raw_payload.get("insight_v1"), dict) else None

    if not force_regenerate and cached and _cache_is_valid(cached, now_utc):
        return cached, {"cache_hit": True, "context_refreshed": False, "llm_used": bool(cached.get("quality", {}).get("llm_used"))}

    context_result = {"refreshed": False, "updated": False, "reason": "skipped"}
    if refresh_context_if_needed and _needs_context_refresh(row, now_utc):
        context_result = await refresh_announcement_context(row, now_utc)

    last_seen_at = _to_utc(getattr(row, "last_seen_at", None))
    context_age_minutes = None
    if last_seen_at is not None:
        context_age_minutes = max(0, int((now_utc - last_seen_at).total_seconds() / 60))

    llm_sections: dict[str, Any] | None = None
    llm_error: str | None = None
    llm_used = False
    if bool(settings.ANNOUNCEMENT_INSIGHT_ENABLED):
        llm_sections, llm_error = await _llm_generate_sections(row)
        llm_used = llm_sections is not None
    else:
        llm_error = "insight_disabled"

    if llm_sections:
        announcement_type = str(getattr(row, "announcement_type", "other") or "other").strip().lower()
        if announcement_type not in _SUPPORTED_TYPES:
            announcement_type = "other"
        severity, severity_score = _severity_for_row(row)
        type_confidence = float(getattr(row, "type_confidence", 0.5) or 0.5)
        insight_payload = {
            "version": "v1",
            "generated_at": now_utc.isoformat(),
            "source": {
                "id": getattr(row, "source_id", None),
                "url": getattr(row, "url", None),
                "canonical_url": getattr(row, "canonical_url", None),
            },
            "headline": getattr(row, "headline", None),
            "classification": {
                "announcement_type": announcement_type,
                "severity": severity,
                "confidence": round(max(type_confidence, severity_score), 3),
            },
            "insight": llm_sections,
            "quality": {
                "llm_used": True,
                "fallback_used": False,
                "context_refreshed": bool(context_result.get("refreshed")),
                "context_age_minutes": context_age_minutes,
                "llm_error": None,
            },
            "research_links": _research_links(row),
        }
    else:
        insight_payload = _fallback_insight(
            row,
            now_utc,
            llm_used=llm_used,
            context_refreshed=bool(context_result.get("refreshed")),
            context_age_minutes=context_age_minutes,
            llm_error=llm_error,
        )

    raw_payload["insight_v1"] = insight_payload
    row.raw_payload = raw_payload
    return insight_payload, {
        "cache_hit": False,
        "context_refreshed": bool(context_result.get("refreshed")),
        "context_refresh_reason": context_result.get("reason"),
        "context_updated": bool(context_result.get("updated")),
        "llm_used": bool(insight_payload.get("quality", {}).get("llm_used")),
        "fallback_used": bool(insight_payload.get("quality", {}).get("fallback_used")),
        "llm_error": insight_payload.get("quality", {}).get("llm_error"),
    }
