from __future__ import annotations

import json
import re

import httpx

from apps.core.config import get_settings
from apps.core.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)


def _extract_json(content: str) -> dict | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def polish_overview(overview: list[str], report_type: str) -> tuple[list[str], bool, str | None]:
    mode = (settings.LLM_MODE or "off").lower()
    if mode == "off":
        return overview, False, None

    prompt = (
        "Rewrite these analyst report bullets for clarity while preserving exact meaning. "
        "No investment advice. Output JSON only as {\"overview\": [..]} with max 6 bullets.\n"
        f"Report type: {report_type}\n"
        f"Bullets: {json.dumps(overview, ensure_ascii=True)}"
    )

    try:
        if mode == "api":
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.post(
                    f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    json={
                        "model": settings.LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 250,
                        "temperature": 0.2,
                        "stream": False,
                    },
                )
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        elif mode == "local":
            async with httpx.AsyncClient(timeout=12) as client:
                resp = await client.post(
                    f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate",
                    json={"model": settings.OLLAMA_MODEL, "prompt": prompt, "stream": False},
                )
            resp.raise_for_status()
            content = resp.json().get("response", "")
        else:
            return overview, False, f"unsupported_llm_mode:{mode}"

        parsed = _extract_json(content)
        if not parsed:
            return overview, False, "llm_invalid_json"

        candidate = parsed.get("overview")
        if not isinstance(candidate, list):
            return overview, False, "llm_missing_overview"

        cleaned = [str(item).strip() for item in candidate if str(item).strip()]
        if not cleaned:
            return overview, False, "llm_empty_overview"

        return cleaned[:6], True, None
    except Exception as exc:  # noqa: PERF203
        logger.warning("analyst_llm_polish_failed", error=str(exc))
        return overview, False, str(exc)
