#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


EXPECTED_BY_ROLE: dict[str, set[str]] = {
    "platform_ops": {
        "agent_runs",
        "email_validation_runs",
        "email_validation_steps",
        "autonomy_state",
        "healing_incidents",
        "learning_summaries",
    },
    "agent_a": {"prices_daily", "index_daily", "fx_daily", "news_headlines_daily", "daily_briefings"},
    "agent_b": {"announcements", "announcement_assets", "source_health"},
    "agent_c": {
        "source_health",
        "sentiment_raw_posts",
        "sentiment_ticker_mentions",
        "sentiment_weekly",
        "sentiment_digest_reports",
        "sentiment_mentions",
        "sentiment_snapshots",
    },
    "agent_d": {"analyst_reports"},
    "agent_e": {"pattern", "pattern_occurrence", "accuracy_score", "outcome_tracking", "impact_stat", "archive_run"},
    "agent_f": {"insight_cards", "evidence_packs", "context_fetch_jobs"},
}


async def _prune(database_url: str, role: str) -> None:
    expected = EXPECTED_BY_ROLE.get(role)
    if expected is None:
        raise ValueError(f"Unknown service role: {role}")

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public'
                    """
                )
            )
            current = {str(r[0]) for r in rows}
            keep = set(expected) | {"alembic_version"}
            to_drop = sorted(current - keep)
            for table_name in to_drop:
                await conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
    finally:
        await engine.dispose()


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: prune_service_tables.py <DATABASE_URL> <service_role>", file=sys.stderr)
        return 2
    asyncio.run(_prune(sys.argv[1], sys.argv[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
