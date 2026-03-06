from __future__ import annotations

from typing import Any

from apps.reporting.composer.summarizer import compose_human_summary_v2


def from_announcements_summary(
    *,
    summary: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = summary or {}
    m = metrics or {}
    core_failed = [str(v) for v in (m.get("core_sources_failed") or []) if str(v).strip()]
    top_types = src.get("top_types") if isinstance(src.get("top_types"), list) else []
    top_tickers = src.get("top_tickers") if isinstance(src.get("top_tickers"), list) else []

    return compose_human_summary_v2(
        headline=str(src.get("headline") or "Announcement monitor update"),
        plain_summary=str(src.get("plain_summary") or "Announcement pipeline completed."),
        key_drivers=[str(v) for v in (src.get("bullets") or [])[:4]],
        risks=[f"core_source_failed:{v}" for v in core_failed[:5]],
        sector_highlights=[
            f"type:{t.get('type')} count:{int(t.get('count') or 0)}"
            for t in top_types[:3]
            if isinstance(t, dict)
        ],
        ticker_insights=[
            {
                "ticker": str(t.get("ticker")),
                "summary": f"Announcement activity count {int(t.get('count') or 0)}",
                "outlook": "watch",
                "confidence": None,
                "evidence_refs": [],
            }
            for t in top_tickers[:6]
            if isinstance(t, dict) and t.get("ticker")
        ],
        quality={
            "coverage_pct": float(m.get("core_sources_passed_count") or 0) / max(float((m.get("core_sources_passed_count") or 0) + (m.get("core_sources_failed_count") or 0)), 1.0) * 100.0,
            "freshness_score": 100.0,
            "confidence_score": 90.0 if not core_failed else 60.0,
            "degradation_flags": core_failed,
        },
        evidence_refs=[],
        next_watch=[f"new_alert_count:{int(m.get('new_alert_count') or 0)}"],
    )
