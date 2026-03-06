from __future__ import annotations

from dataclasses import dataclass
import json
import re

import httpx

from apps.core.config import get_settings
from apps.core.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)


@dataclass(slots=True)
class LLMSentiment:
    score: float
    label: str
    confidence: float
    reason: str


def _extract_json(content: str) -> dict | None:
    if not content:
        return None
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    m = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group(0))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def llm_refine_sentiment(text: str, ticker: str) -> LLMSentiment | None:
    mode = (settings.LLM_MODE or "off").lower()
    if mode == "off":
        return None

    prompt = (
        "Classify sentiment for this text about the stock ticker.\n"
        "Respond JSON only with keys: label, score, confidence, reason.\n"
        "label must be bullish|bearish|neutral; score in [-1,1]; confidence in [0,1].\n"
        f"Ticker: {ticker}\n"
        f"Text: {text[:2000]}"
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
                        "max_tokens": 160,
                        "temperature": 0,
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
            return None

        parsed = _extract_json(content)
        if not parsed:
            return None
        label = str(parsed.get("label", "")).lower().strip()
        if label not in {"bullish", "bearish", "neutral"}:
            return None
        score = float(parsed.get("score", 0))
        confidence = float(parsed.get("confidence", 0))
        reason = str(parsed.get("reason", "")).strip()
        score = max(-1.0, min(1.0, score))
        confidence = max(0.0, min(1.0, confidence))
        return LLMSentiment(score=round(score, 3), label=label, confidence=round(confidence, 3), reason=reason)
    except Exception as exc:
        logger.warning("sentiment_llm_failed", error=str(exc))
        return None

