from __future__ import annotations

from typing import Any

from apps.reporting.composer.summarizer import compose_human_summary_v2


def from_report_summary(
    *,
    summary: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = summary or {}
    m = metrics or {}
    coverage = src.get("coverage") if isinstance(src.get("coverage"), dict) else {}
    upstream_quality = m.get("upstream_quality") if isinstance(m.get("upstream_quality"), dict) else {}
    degradation_flags = []
    if bool(m.get("degraded")):
        degradation_flags.append("degraded_upstream_inputs")
    if m.get("feedback_warning"):
        degradation_flags.append(str(m.get("feedback_warning")))
    decision_trace = m.get("decision_trace") if isinstance(m.get("decision_trace"), list) else []
    evidence_refs = []
    for idx, row in enumerate(decision_trace[:10]):
        evidence_refs.append(
            {
                "type": "decision_trace",
                "source_id": "agent_d",
                "timestamp": None,
                "url_or_id": f"trace:{idx}",
                "confidence": None,
            }
        )

    return compose_human_summary_v2(
        headline=str(src.get("headline") or "Analyst report generated."),
        plain_summary=str(src.get("plain_summary") or "Cross-agent synthesis completed."),
        key_drivers=[str(v) for v in (src.get("bullets") or [])[:4]],
        risks=[str(v) for v in degradation_flags],
        sector_highlights=[],
        ticker_insights=[],
        quality={
            "coverage_pct": float(coverage.get("tickers_covered") or 0.0),
            "freshness_score": float(upstream_quality.get("availability_pct") or 0.0),
            "confidence_score": float(upstream_quality.get("score") or 0.0),
            "degradation_flags": degradation_flags,
        },
        evidence_refs=evidence_refs,
        next_watch=[str(v) for v in (m.get("status_reason"),) if v],
    )
