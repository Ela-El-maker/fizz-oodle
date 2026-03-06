from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

import httpx
import yaml

from apps.agents.announcements.severity import derive_severity
from apps.core.config import get_settings
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()
CLASSIFIER_VERSION = "rule-v1"


@dataclass(slots=True)
class ClassificationResult:
    announcement_type: str
    confidence: float
    severity: str = "low"
    severity_score: float = 0.25
    llm_used: bool = False
    llm_attempted: bool = False
    llm_error_type: str | None = None
    classification_path: str = "rule"


def _load_classifier_map() -> dict[str, list[str]]:
    path = Path(settings.ANNOUNCEMENT_TYPES_CONFIG_PATH)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[3] / settings.ANNOUNCEMENT_TYPES_CONFIG_PATH).resolve()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("classifier_keywords", {})


def _rule_classify(text: str) -> ClassificationResult:
    classifier_map = _load_classifier_map()
    lowered = (text or "").lower()

    best_type = "other"
    best_hits = 0
    total_hits = 0
    for announcement_type, keywords in classifier_map.items():
        hits = 0
        for keyword in keywords:
            if keyword.lower() in lowered:
                hits += 1
        total_hits += hits
        if hits > best_hits:
            best_hits = hits
            best_type = announcement_type

    if total_hits == 0:
        severity, severity_score = derive_severity("other", 0.25)
        return ClassificationResult(
            "other",
            0.25,
            severity=severity,
            severity_score=severity_score,
            llm_used=False,
            classification_path="rule",
        )

    confidence = min(0.95, 0.45 + (best_hits / max(1, total_hits)) * 0.5)
    conf = round(confidence, 3)
    severity, severity_score = derive_severity(best_type, conf)
    return ClassificationResult(
        best_type,
        conf,
        severity=severity,
        severity_score=severity_score,
        llm_used=False,
        classification_path="rule",
    )


def _extract_json_type(content: str) -> str | None:
    if not content:
        return None

    # Prefer JSON object if present.
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and isinstance(parsed.get("announcement_type"), str):
            return parsed["announcement_type"]
    except Exception:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and isinstance(parsed.get("announcement_type"), str):
                return parsed["announcement_type"]
        except Exception:
            return None

    return None


def _classify_llm_error(exc: Exception) -> str:
    if isinstance(exc, (httpx.TimeoutException, httpx.ReadTimeout)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "network"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return "rate_limited"
        if code in {401, 403}:
            return "auth"
        if code >= 500:
            return "upstream_5xx"
        return "http_error"
    return "unknown_error"


async def _llm_fallback(headline: str, details: str | None) -> tuple[str | None, str | None, bool]:
    mode = (settings.LLM_MODE or "off").lower()
    if mode == "off":
        return None, "llm_disabled", False

    prompt = (
        "Classify this stock-market announcement into exactly one type from: "
        "dividend, earnings, regulatory_filing, rights_issue, merger_acquisition, "
        "board_change, profit_warning, agm_egm, trading_suspension, other. "
        "Respond JSON only: {\"announcement_type\":\"...\"}.\n\n"
        f"Headline: {headline}\n"
        f"Details: {details or ''}"
    )

    if mode == "api":
        if not settings.LLM_API_KEY:
            return None, "missing_api_key", False
        try:
            timeout_seconds = max(1, int(settings.ANNOUNCEMENT_LLM_TIMEOUT_SECONDS))
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    json={
                        "model": settings.LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 120,
                        "temperature": 0,
                        "stream": False,
                    },
                )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
            return _extract_json_type(content), None, True
        except Exception as exc:
            error_type = _classify_llm_error(exc)
            logger.warning("classification_llm_failed", error_type=error_type, error=str(exc))
            return None, error_type, True

    if mode == "local":
        try:
            timeout_seconds = max(1, int(settings.ANNOUNCEMENT_LLM_TIMEOUT_SECONDS))
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                    json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
            response.raise_for_status()
            content = response.json().get("response", "")
            return _extract_json_type(content), None, True
        except Exception as exc:
            error_type = _classify_llm_error(exc)
            logger.warning("classification_llm_failed", error_type=error_type, error=str(exc))
            return None, error_type, True

    return None, "invalid_mode", False


async def classify_announcement(
    headline: str,
    details: str | None,
    *,
    allow_llm: bool = True,
) -> ClassificationResult:
    text = "\n".join(part for part in [headline, details or ""] if part)
    result = _rule_classify(text)

    threshold = float(settings.ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD)
    if result.confidence >= threshold:
        return result

    if not allow_llm:
        result.classification_path = "rule_no_llm_budget"
        return result

    llm_type, llm_error_type, llm_attempted = await _llm_fallback(headline, details)
    classifier_map = _load_classifier_map()
    if llm_type and llm_type in classifier_map:
        conf = max(result.confidence, threshold)
        severity, severity_score = derive_severity(llm_type, conf)
        return ClassificationResult(
            llm_type,
            conf,
            severity=severity,
            severity_score=severity_score,
            llm_used=True,
            llm_attempted=llm_attempted,
            classification_path="llm",
        )

    result.llm_attempted = llm_attempted
    result.llm_error_type = llm_error_type
    result.classification_path = "rule_fallback_llm_error" if llm_error_type else "rule_fallback"
    return result
