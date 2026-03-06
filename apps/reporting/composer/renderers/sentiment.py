from __future__ import annotations

from typing import Any

from apps.reporting.composer.summarizer import compose_human_summary_v2


def from_sentiment_summary(
    *,
    summary: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = summary or {}
    m = metrics or {}
    coverage = src.get("coverage") if isinstance(src.get("coverage"), dict) else {}
    signal = int(coverage.get("tickers_with_signal") or 0)
    total = int(coverage.get("total_tickers") or 0)

    return compose_human_summary_v2(
        headline=str(src.get("headline") or "Weekly sentiment update"),
        plain_summary=str(src.get("plain_summary") or "Sentiment digest generated."),
        key_drivers=[str(v) for v in (src.get("bullets") or [])[:4]],
        risks=[],
        sector_highlights=[],
        ticker_insights=[],
        quality={
            "coverage_pct": (signal / max(total, 1)) * 100.0 if total else 0.0,
            "freshness_score": 100.0,
            "confidence_score": float(m.get("avg_confidence") or 0.0) * 100.0 if m.get("avg_confidence") is not None else 0.0,
            "degradation_flags": [str(v) for v in (m.get("core_sources_failed") or [])[:5]],
        },
        evidence_refs=[],
        next_watch=[str(v) for v in (src.get("leaders", {}) or {}).get("bullish", [])[:3]],
    )
