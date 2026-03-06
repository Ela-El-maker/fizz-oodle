"""Cross-agent data quality engine.

Validates freshness, completeness, and consistency of data flowing
between agents.  Called by the healing engine or on-demand from ops.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from apps.core.config import get_settings
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class QualityCheck:
    agent: str
    check: str
    passed: bool
    detail: str
    severity: str = "warning"  # info | warning | critical


@dataclass
class QualityReport:
    generated_at: str = ""
    checks: list[QualityCheck] = field(default_factory=list)
    score: float = 1.0  # 0.0 – 1.0  aggregate quality score

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "critical")

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "score": round(self.score, 3),
            "passed": self.passed,
            "total_checks": len(self.checks),
            "failed_checks": sum(1 for c in self.checks if not c.passed),
            "checks": [
                {
                    "agent": c.agent,
                    "check": c.check,
                    "passed": c.passed,
                    "detail": c.detail,
                    "severity": c.severity,
                }
                for c in self.checks
            ],
        }


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def check_freshness(
    agent: str,
    latest_at: datetime | str | None,
    max_age_hours: float,
    *,
    severity: str = "warning",
) -> QualityCheck:
    """Verify that the most recent output is within max_age_hours."""
    if latest_at is None:
        return QualityCheck(
            agent=agent,
            check="freshness",
            passed=False,
            detail="No output timestamp available",
            severity=severity,
        )
    if isinstance(latest_at, str):
        try:
            latest_at = datetime.fromisoformat(latest_at.replace("Z", "+00:00"))
        except ValueError:
            return QualityCheck(
                agent=agent, check="freshness", passed=False,
                detail=f"Unparseable timestamp: {latest_at!r}", severity=severity,
            )
    if latest_at.tzinfo is None:
        latest_at = latest_at.replace(tzinfo=timezone.utc)
    age = _now_utc() - latest_at
    age_hours = age.total_seconds() / 3600
    ok = age_hours <= max_age_hours
    return QualityCheck(
        agent=agent,
        check="freshness",
        passed=ok,
        detail=f"Age {age_hours:.1f}h (max {max_age_hours}h)",
        severity=severity,
    )


def check_completeness(
    agent: str,
    items_count: int,
    min_expected: int,
    *,
    label: str = "items",
    severity: str = "warning",
) -> QualityCheck:
    """Verify that the output meets a minimum row count."""
    ok = items_count >= min_expected
    return QualityCheck(
        agent=agent,
        check="completeness",
        passed=ok,
        detail=f"{items_count} {label} (min {min_expected})",
        severity=severity,
    )


def check_cross_agent_consistency(
    *,
    briefing_tickers: set[str],
    announcement_tickers: set[str],
    sentiment_tickers: set[str],
    universe_tickers: set[str],
) -> list[QualityCheck]:
    """Detect ticker coverage gaps between agents and the universe."""
    checks: list[QualityCheck] = []

    missing_from_briefing = universe_tickers - briefing_tickers
    if missing_from_briefing:
        checks.append(QualityCheck(
            agent="briefing",
            check="ticker_coverage",
            passed=len(missing_from_briefing) <= 3,
            detail=f"{len(missing_from_briefing)} universe tickers missing: {', '.join(sorted(missing_from_briefing)[:5])}",
            severity="warning",
        ))
    else:
        checks.append(QualityCheck(
            agent="briefing", check="ticker_coverage", passed=True, detail="All universe tickers covered",
        ))

    orphan_announcements = announcement_tickers - universe_tickers
    if orphan_announcements:
        checks.append(QualityCheck(
            agent="announcements",
            check="orphan_tickers",
            passed=True,  # informational
            detail=f"{len(orphan_announcements)} tickers not in universe: {', '.join(sorted(orphan_announcements)[:5])}",
            severity="info",
        ))

    missing_sentiment = universe_tickers - sentiment_tickers
    if len(missing_sentiment) > len(universe_tickers) * 0.3:
        checks.append(QualityCheck(
            agent="sentiment",
            check="ticker_coverage",
            passed=False,
            detail=f"{len(missing_sentiment)}/{len(universe_tickers)} universe tickers missing from sentiment",
            severity="warning",
        ))
    else:
        checks.append(QualityCheck(
            agent="sentiment", check="ticker_coverage", passed=True,
            detail=f"{len(universe_tickers) - len(missing_sentiment)}/{len(universe_tickers)} covered",
        ))

    return checks


def check_schema_fields(
    agent: str,
    item: dict[str, Any],
    required_fields: list[str],
    *,
    severity: str = "warning",
) -> QualityCheck:
    """Verify that a data item contains the mandatory fields."""
    missing = [f for f in required_fields if f not in item or item[f] is None]
    if missing:
        return QualityCheck(
            agent=agent,
            check="schema_fields",
            passed=False,
            detail=f"Missing fields: {', '.join(missing)}",
            severity=severity,
        )
    return QualityCheck(
        agent=agent, check="schema_fields", passed=True, detail="All required fields present",
    )


async def run_quality_audit(
    *,
    briefing_latest: dict[str, Any] | None = None,
    announcements_stats: dict[str, Any] | None = None,
    sentiment_latest: dict[str, Any] | None = None,
    analyst_latest: dict[str, Any] | None = None,
    patterns_summary: dict[str, Any] | None = None,
    universe_tickers: set[str] | None = None,
) -> QualityReport:
    """Run the full cross-agent data quality audit.

    Callers pass in pre-fetched payloads from each agent's API.
    Returns a QualityReport with individual check results + aggregate score.
    """
    report = QualityReport(generated_at=_now_utc().isoformat())
    checks: list[QualityCheck] = []

    # --- Briefing freshness and completeness ---
    if briefing_latest and isinstance(briefing_latest, dict):
        item = briefing_latest.get("item") if isinstance(briefing_latest.get("item"), dict) else briefing_latest
        checks.append(check_freshness("briefing", item.get("generated_at") or item.get("briefing_date"), max_age_hours=26, severity="warning"))
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        price_count = int(metrics.get("prices_collected") or 0)
        checks.append(check_completeness("briefing", price_count, min_expected=10, label="prices", severity="warning"))
    else:
        checks.append(QualityCheck(agent="briefing", check="availability", passed=False, detail="No briefing data available", severity="warning"))

    # --- Announcements freshness ---
    if announcements_stats and isinstance(announcements_stats, dict):
        total = int(announcements_stats.get("total") or 0)
        alerted = int(announcements_stats.get("alerted") or 0)
        checks.append(check_completeness("announcements", total, min_expected=1, label="announcements", severity="info"))
        if total > 0 and alerted == 0:
            checks.append(QualityCheck(
                agent="announcements", check="alert_ratio", passed=True,
                detail=f"0/{total} alerted (may be normal during quiet periods)", severity="info",
            ))
    else:
        checks.append(QualityCheck(agent="announcements", check="availability", passed=False, detail="No announcements stats available", severity="warning"))

    # --- Sentiment freshness ---
    if sentiment_latest and isinstance(sentiment_latest, dict):
        item = sentiment_latest.get("item") if isinstance(sentiment_latest.get("item"), dict) else sentiment_latest
        checks.append(check_freshness("sentiment", item.get("generated_at") or item.get("week_start"), max_age_hours=7 * 24 + 12, severity="warning"))
    else:
        checks.append(QualityCheck(agent="sentiment", check="availability", passed=False, detail="No sentiment digest available", severity="warning"))

    # --- Analyst freshness ---
    if analyst_latest and isinstance(analyst_latest, dict):
        item = analyst_latest.get("item") if isinstance(analyst_latest.get("item"), dict) else analyst_latest
        checks.append(check_freshness("analyst", item.get("generated_at") or item.get("created_at"), max_age_hours=26, severity="warning"))
        checks.append(check_schema_fields("analyst", item, ["human_summary", "status", "period_key"]))
    else:
        checks.append(QualityCheck(agent="analyst", check="availability", passed=False, detail="No analyst report available", severity="warning"))

    # --- Patterns ---
    if patterns_summary and isinstance(patterns_summary, dict):
        active = int(patterns_summary.get("active_count") or patterns_summary.get("active") or 0)
        checks.append(check_completeness("archivist", active, min_expected=0, label="active patterns", severity="info"))
    else:
        checks.append(QualityCheck(agent="archivist", check="availability", passed=False, detail="No patterns summary available", severity="info"))

    # --- Cross-agent consistency ---
    if universe_tickers:
        briefing_tickers: set[str] = set()
        announcement_tickers: set[str] = set()
        sentiment_tickers: set[str] = set()

        if briefing_latest and isinstance(briefing_latest, dict):
            item = briefing_latest.get("item") if isinstance(briefing_latest.get("item"), dict) else briefing_latest
            for p in (item.get("prices") or []):
                if isinstance(p, dict) and p.get("ticker"):
                    briefing_tickers.add(str(p["ticker"]).upper())

        if announcements_stats and isinstance(announcements_stats, dict):
            for ticker in (announcements_stats.get("by_ticker") or {}).keys():
                announcement_tickers.add(str(ticker).upper())

        if sentiment_latest and isinstance(sentiment_latest, dict):
            for row in (sentiment_latest.get("items") or []):
                if isinstance(row, dict) and row.get("ticker"):
                    sentiment_tickers.add(str(row["ticker"]).upper())

        checks.extend(check_cross_agent_consistency(
            briefing_tickers=briefing_tickers,
            announcement_tickers=announcement_tickers,
            sentiment_tickers=sentiment_tickers,
            universe_tickers=universe_tickers,
        ))

    # --- Aggregate score ---
    if checks:
        weights = {"critical": 3.0, "warning": 1.0, "info": 0.3}
        total_weight = sum(weights.get(c.severity, 1.0) for c in checks)
        passed_weight = sum(weights.get(c.severity, 1.0) for c in checks if c.passed)
        report.score = passed_weight / total_weight if total_weight > 0 else 1.0

    report.checks = checks
    logger.info(
        "data_quality_audit",
        score=round(report.score, 3),
        total=len(checks),
        failed=sum(1 for c in checks if not c.passed),
    )
    return report
