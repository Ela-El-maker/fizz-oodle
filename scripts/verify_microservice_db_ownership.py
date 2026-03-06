#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@dataclass(frozen=True)
class DbExpectation:
    db_name: str
    expected_tables: tuple[str, ...]


EXPECTED: tuple[DbExpectation, ...] = (
    DbExpectation("db_platform_ops", ("agent_runs",)),
    DbExpectation(
        "db_agent_a",
        ("daily_briefings", "fx_daily", "index_daily", "news_headlines_daily", "prices_daily"),
    ),
    DbExpectation("db_agent_b", ("announcement_assets", "announcements", "source_health")),
    DbExpectation(
        "db_agent_c",
        (
            "sentiment_digest_reports",
            "sentiment_mentions",
            "sentiment_raw_posts",
            "sentiment_snapshots",
            "sentiment_ticker_mentions",
            "sentiment_weekly",
            "source_health",
        ),
    ),
    DbExpectation("db_agent_d", ("analyst_reports",)),
    DbExpectation("db_agent_e", ("accuracy_score", "archive_run", "impact_stat", "outcome_tracking", "pattern", "pattern_occurrence")),
)


def _database_url(db_name: str) -> str:
    user = os.getenv("DB_USER", "marketintel")
    password = os.getenv("DB_PASSWORD", "marketintel")
    host = os.getenv("DB_HOST", "postgres")
    port = os.getenv("DB_PORT", "5432")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"


async def _tables_for_db(db_name: str) -> list[str]:
    engine = create_async_engine(_database_url(db_name))
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                    """
                )
            )
            return [str(r[0]) for r in rows]
    finally:
        await engine.dispose()


async def main() -> int:
    report: dict = {"status": "ok", "databases": []}
    failures = 0

    for cfg in EXPECTED:
        actual = await _tables_for_db(cfg.db_name)
        actual_without_alembic = [t for t in actual if t != "alembic_version"]
        expected = sorted(cfg.expected_tables)
        extras = sorted(set(actual_without_alembic) - set(expected))
        missing = sorted(set(expected) - set(actual_without_alembic))
        db_status = "ok" if not extras and not missing else "fail"
        if db_status == "fail":
            failures += 1

        report["databases"].append(
            {
                "db_name": cfg.db_name,
                "status": db_status,
                "expected_tables": expected,
                "actual_tables": actual_without_alembic,
                "missing_tables": missing,
                "extra_tables": extras,
                "has_alembic_version": "alembic_version" in actual,
            }
        )

    if failures:
        report["status"] = "fail"

    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
