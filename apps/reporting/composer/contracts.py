from __future__ import annotations

from typing import Any, TypedDict


class EvidenceRef(TypedDict, total=False):
    type: str
    source_id: str
    timestamp: str | None
    url_or_id: str
    confidence: float | None


class TickerInsight(TypedDict, total=False):
    ticker: str
    summary: str
    outlook: str
    confidence: float | None
    evidence_refs: list[EvidenceRef]


class InsightQuality(TypedDict, total=False):
    coverage_pct: float
    freshness_score: float
    confidence_score: float
    degradation_flags: list[str]


class HumanSummaryV2(TypedDict, total=False):
    headline: str
    plain_summary: str
    key_drivers: list[str]
    risks: list[str]
    sector_highlights: list[str]
    ticker_insights: list[TickerInsight]
    quality: InsightQuality
    evidence_refs: list[EvidenceRef]
    next_watch: list[str]


def default_quality() -> InsightQuality:
    return {
        "coverage_pct": 0.0,
        "freshness_score": 0.0,
        "confidence_score": 0.0,
        "degradation_flags": [],
    }


def empty_summary() -> HumanSummaryV2:
    return {
        "headline": "No insight available for this cycle.",
        "plain_summary": "The system did not receive enough reliable inputs to generate a narrative.",
        "key_drivers": [],
        "risks": ["insufficient_signal"],
        "sector_highlights": [],
        "ticker_insights": [],
        "quality": default_quality(),
        "evidence_refs": [],
        "next_watch": [],
    }


def to_jsonable(summary: HumanSummaryV2 | dict[str, Any]) -> dict[str, Any]:
    # Keeps payload stable for DB JSON fields and FastAPI serialization.
    return dict(summary or {})
