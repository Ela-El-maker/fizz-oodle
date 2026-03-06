from __future__ import annotations

from typing import Any

from apps.reporting.composer.summarizer import compose_human_summary_v2


def from_archive_summary(
    *,
    summary: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = summary or {}
    m = metrics or {}
    coverage = src.get("coverage") if isinstance(src.get("coverage"), dict) else {}
    degraded = bool((src.get("flags") or {}).get("degraded") or m.get("degraded"))

    return compose_human_summary_v2(
        headline=str(src.get("headline") or "Archivist memory update"),
        plain_summary=str(src.get("plain_summary") or "Pattern and impact archive updated."),
        key_drivers=[str(v) for v in (src.get("bullets") or [])[:4]],
        risks=["upstream_quality_low"] if degraded else [],
        sector_highlights=[],
        ticker_insights=[],
        quality={
            "coverage_pct": float(coverage.get("reports_considered") or 0.0),
            "freshness_score": 100.0,
            "confidence_score": float(coverage.get("upstream_quality_score") or 0.0),
            "degradation_flags": ["degraded"] if degraded else [],
        },
        evidence_refs=[],
        next_watch=[
            f"patterns_upserted:{int(coverage.get('patterns_upserted') or 0)}",
            f"impacts_upserted:{int(coverage.get('impacts_upserted') or 0)}",
        ],
    )
