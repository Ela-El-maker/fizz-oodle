from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any

import httpx

from apps.agents.briefing.types import MarketBrief
from apps.core.config import get_settings
from apps.core.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)


def _extract_json_object(content: str) -> dict[str, Any] | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _normalize_confidence_level(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _build_fallback(context: dict[str, Any], error: str | None = None) -> tuple[MarketBrief, str]:
    breadth = context.get("market_breadth", {}) if isinstance(context, dict) else {}
    advancers = int(breadth.get("advancers_count", 0) or 0)
    decliners = int(breadth.get("decliners_count", 0) or 0)
    top = context.get("top_movers", []) if isinstance(context, dict) else []
    top_item = top[0] if top else {}
    top_ticker = str(top_item.get("ticker") or "N/A")
    top_pct = top_item.get("pct_change")
    nasi = context.get("nasi", {}) if isinstance(context, dict) else {}
    nasi_value = nasi.get("value")
    nasi_pct = nasi.get("pct_change")
    pulse = (
        f"Market breadth shows {advancers} advancers and {decliners} decliners. "
        f"NASI is at {nasi_value if nasi_value is not None else 'N/A'}"
        f"{f' ({nasi_pct}%)' if nasi_pct is not None else ''}."
    )
    narrative = (
        f"Top observed mover is {top_ticker}"
        f"{f' at {top_pct:.2f}%' if isinstance(top_pct, (int, float)) else ''}. "
        "Signals are generated from available source data only."
    )
    unusual = context.get("unusual_signals", []) if isinstance(context, dict) else []
    if not unusual:
        unusual = ["No strong anomaly detected from available inputs."]
    brief = MarketBrief(
        market_pulse=pulse,
        drivers=[
            "Breadth and index movement are used to infer broad market tone.",
            "Top movers and headline overlap are used to flag concentration.",
        ],
        unusual_signals=[str(x) for x in unusual][:3],
        narrative_interpretation=narrative,
        confidence_level="medium",
        confidence_score=0.5,
        confidence_reason="fallback_template",
        model=settings.LLM_MODEL,
        provider=settings.LLM_PROVIDER,
        llm_used=False,
        llm_error=error,
    )
    rendered = " ".join(
        [
            brief.market_pulse,
            " ".join(brief.drivers[:2]),
            " ".join(brief.unusual_signals[:1]),
            brief.narrative_interpretation,
            f"Confidence: {brief.confidence_level}.",
        ]
    ).strip()
    return brief, rendered


def _render_from_brief(brief: MarketBrief) -> str:
    pieces = [
        brief.market_pulse.strip(),
        " ".join(x.strip() for x in brief.drivers if str(x).strip())[:420],
        " ".join(x.strip() for x in brief.unusual_signals if str(x).strip())[:280],
        brief.narrative_interpretation.strip(),
        f"Confidence: {brief.confidence_level} ({brief.confidence_score:.2f}).",
    ]
    return " ".join(part for part in pieces if part).strip()


def _coerce_market_brief(payload: dict[str, Any]) -> MarketBrief | None:
    if not isinstance(payload, dict):
        return None
    market_pulse = str(payload.get("market_pulse") or "").strip()
    narrative = str(payload.get("narrative_interpretation") or "").strip()
    if not market_pulse or not narrative:
        return None
    drivers = payload.get("drivers") or []
    unusual = payload.get("unusual_signals") or []
    if not isinstance(drivers, list):
        drivers = [str(drivers)]
    if not isinstance(unusual, list):
        unusual = [str(unusual)]
    confidence_score = float(payload.get("confidence_score") or 0.5)
    confidence_score = max(0.0, min(1.0, confidence_score))
    confidence_level = str(payload.get("confidence_level") or _normalize_confidence_level(confidence_score)).lower().strip()
    if confidence_level not in {"high", "medium", "low"}:
        confidence_level = _normalize_confidence_level(confidence_score)
    confidence_reason = str(payload.get("confidence_reason") or "model_assessment").strip()
    return MarketBrief(
        market_pulse=market_pulse,
        drivers=[str(x).strip() for x in drivers if str(x).strip()][:4],
        unusual_signals=[str(x).strip() for x in unusual if str(x).strip()][:4],
        narrative_interpretation=narrative,
        confidence_level=confidence_level,
        confidence_score=confidence_score,
        confidence_reason=confidence_reason,
        model=str(payload.get("model") or settings.LLM_MODEL),
        provider=str(payload.get("provider") or settings.LLM_PROVIDER),
        llm_used=True,
        llm_error=None,
    )


def _prompt(context_json: str) -> str:
    return (
        "You are a quantitative market analyst embedded inside our market intelligence system.\n"
        "Use only the provided JSON context. Do not invent events.\n"
        "Return JSON only with keys: market_pulse,drivers,unusual_signals,narrative_interpretation,"
        "confidence_level,confidence_score,confidence_reason,model,provider.\n"
        "confidence_level must be high|medium|low and confidence_score in [0,1].\n"
        "Keep market_pulse and narrative concise but informative.\n"
        f"Context JSON:\n{context_json}"
    )


async def generate_market_brief(context: dict[str, Any]) -> tuple[MarketBrief, str]:
    mode = (settings.LLM_MODE or "off").lower()
    if mode == "off":
        return _build_fallback(context, error="llm_disabled")
    if mode != "api":
        return _build_fallback(context, error=f"unsupported_llm_mode:{mode}")
    if not settings.LLM_API_KEY:
        return _build_fallback(context, error="missing_api_key")

    payload_context = json.dumps(context, ensure_ascii=True, default=str)
    request = {
        "model": settings.LLM_MODEL,
        "messages": [{"role": "user", "content": _prompt(payload_context)}],
        "max_tokens": max(80, int(settings.AGENT_A_BRIEF_LLM_MAX_TOKENS)),
        "temperature": 0.1,
        "stream": False,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=max(5, int(settings.AGENT_A_BRIEF_LLM_TIMEOUT_SECONDS))) as client:
            response = await client.post(
                f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                json=request,
            )
        response.raise_for_status()
        content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _extract_json_object(content)
        brief = _coerce_market_brief(parsed or {})
        if brief is None:
            return _build_fallback(context, error="llm_invalid_json")
        rendered = _render_from_brief(brief)
        return brief, rendered
    except Exception as exc:  # noqa: PERF203
        error = str(exc)
        logger.warning("agent_a_llm_brief_failed", error=error)
        brief, rendered = _build_fallback(context, error=error)
        return brief, rendered


def market_brief_to_dict(brief: MarketBrief) -> dict[str, Any]:
    return asdict(brief)

