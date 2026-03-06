from __future__ import annotations

from typing import Any

from apps.reporting.composer.summarizer import compose_human_summary_v2


def from_briefing_summary(
    *,
    summary: dict[str, Any] | None,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = summary or {}
    m = metrics or {}
    channel_quality = m.get("channel_quality") if isinstance(m.get("channel_quality"), dict) else {}
    degraded = [k for k, v in channel_quality.items() if isinstance(v, dict) and v.get("status") != "success"]
    return compose_human_summary_v2(
        headline=str(src.get("headline") or "Daily market briefing is ready."),
        plain_summary=str(src.get("plain_summary") or "Core market channels were processed."),
        key_drivers=[str(v) for v in (src.get("bullets") or [])[:4]],
        risks=[f"channel_degraded:{k}" for k in degraded[:4]],
        sector_highlights=[],
        ticker_insights=[
            {
                "ticker": str(item.get("ticker")),
                "summary": f"Move {float(item.get('pct_change', 0.0)):+.2f}%",
                "outlook": str(item.get("direction", "neutral")),
                "confidence": None,
                "evidence_refs": [],
            }
            for item in (src.get("top_movers") or [])[:5]
            if isinstance(item, dict) and item.get("ticker")
        ],
        quality={
            "coverage_pct": float(m.get("coverage_ratio", 0.0)) * 100.0 if m.get("coverage_ratio") is not None else 0.0,
            "freshness_score": 100.0,
            "confidence_score": float(((src.get("confidence") or {}).get("score")) or 0.0) * 100.0,
            "degradation_flags": degraded,
        },
        evidence_refs=[],
        next_watch=[str(v) for v in (src.get("bullets") or [])[4:7]],
    )
