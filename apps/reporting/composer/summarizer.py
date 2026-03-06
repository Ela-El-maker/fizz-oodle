from __future__ import annotations

from typing import Any

from apps.reporting.composer.contracts import HumanSummaryV2, default_quality
from apps.reporting.composer.evidence import dedupe_evidence
from apps.reporting.composer.narrative_rules import inject_uncertainty, style_lint


def compose_human_summary_v2(
    *,
    headline: str,
    plain_summary: str,
    key_drivers: list[str] | None = None,
    risks: list[str] | None = None,
    sector_highlights: list[str] | None = None,
    ticker_insights: list[dict[str, Any]] | None = None,
    quality: dict[str, Any] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
    next_watch: list[str] | None = None,
) -> HumanSummaryV2:
    payload: HumanSummaryV2 = {
        "headline": headline.strip() if headline else "Market insight update",
        "plain_summary": plain_summary.strip() if plain_summary else "No additional analyst commentary.",
        "key_drivers": list(key_drivers or []),
        "risks": list(risks or []),
        "sector_highlights": list(sector_highlights or []),
        "ticker_insights": list(ticker_insights or []),
        "quality": dict(default_quality(), **(quality or {})),
        "evidence_refs": dedupe_evidence((evidence_refs or []), limit=24),
        "next_watch": list(next_watch or []),
    }
    styled = style_lint(payload)
    return inject_uncertainty(styled)  # type: ignore[return-value]
