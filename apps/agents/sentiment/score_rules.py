from __future__ import annotations

from dataclasses import dataclass
import re

from apps.core.config import get_settings

settings = get_settings()

MODEL_VERSION = "sentiment_rules_v1"

BULL_WORDS = [
    "bullish",
    "buy",
    "upside",
    "outperform",
    "strong results",
    "record profit",
    "growth",
    "dividend",
    "breakout",
    "undervalued",
]
BEAR_WORDS = [
    "bearish",
    "sell",
    "downside",
    "underperform",
    "weak results",
    "loss",
    "profit warning",
    "overvalued",
    "crash",
    "decline",
]
NEUTRAL_DAMPENERS = ["maybe", "uncertain", "not sure", "rumour", "rumor", "could"]
INTENSIFIERS = ["very", "extremely", "strongly", "massive"]


@dataclass(slots=True)
class RuleScore:
    score: float
    label: str
    confidence: float
    reasons: dict


def _count_hits(text: str, keywords: list[str]) -> int:
    hits = 0
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            hits += 1
    return hits


def score_text(text: str) -> RuleScore:
    lowered = (text or "").lower()
    bull = _count_hits(lowered, BULL_WORDS)
    bear = _count_hits(lowered, BEAR_WORDS)
    damp = _count_hits(lowered, NEUTRAL_DAMPENERS)
    intens = _count_hits(lowered, INTENSIFIERS)

    # Simple negation correction for key cues.
    if re.search(r"\bnot\s+(bullish|buy|strong|growth|good)\b", lowered):
        bull = max(0, bull - 1)
        bear += 1
    if re.search(r"\bnot\s+(bearish|sell|weak|bad)\b", lowered):
        bear = max(0, bear - 1)
        bull += 1

    raw = float(bull - bear)
    if intens > 0 and raw != 0:
        raw *= min(1.5, 1 + 0.15 * intens)
    if damp > 0:
        raw *= max(0.6, 1 - 0.15 * damp)

    denom = max(1.0, float(bull + bear + damp))
    score = max(-1.0, min(1.0, raw / denom))

    bull_th = float(settings.SENTIMENT_THRESHOLD_BULL)
    bear_th = float(settings.SENTIMENT_THRESHOLD_BEAR)
    if score >= bull_th:
        label = "bullish"
    elif score <= bear_th:
        label = "bearish"
    else:
        label = "neutral"

    signal_hits = bull + bear
    if signal_hits == 0:
        confidence = 0.30
    else:
        confidence = min(0.95, 0.40 + 0.1 * signal_hits + 0.1 * abs(score))

    return RuleScore(
        score=round(score, 3),
        label=label,
        confidence=round(confidence, 3),
        reasons={
            "bull_hits": bull,
            "bear_hits": bear,
            "dampeners": damp,
            "intensifiers": intens,
        },
    )

