from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from apps.agents.announcements import pipeline
from apps.agents.announcements.classify import ClassificationResult
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.core import database as db
from apps.core.database import Base


async def _db_ready() -> bool:
    try:
        async with db._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _reset_db() -> None:
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "TRUNCATE TABLE announcement_assets, announcements, source_health, agent_runs, companies "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.mark.asyncio
async def test_agent_b_llm_breaker_opens_and_skips_remaining_items(monkeypatch) -> None:
    if not await _db_ready():
        pytest.skip("Postgres not available for e2e")

    await _reset_db()

    source_ok = SourceConfig(
        source_id="nse_official",
        type="official",
        base_url="https://example.com",
        enabled_by_default=True,
        parser="x",
        timeout_secs=10,
        retries=0,
        backoff_base=2.0,
        rate_limit_rps=1.0,
        ticker_strategy="headline_regex",
        tier="core",
        required_for_success=True,
    )

    async def fake_seed_companies():
        return None

    async def fake_extract_details(_url: str):
        return None

    async def collector_ok(_source):
        return [
            RawAnnouncement(
                source_id="nse_official",
                headline="Market update item one",
                url="https://example.com/a1",
                published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            ),
            RawAnnouncement(
                source_id="nse_official",
                headline="Market update item two",
                url="https://example.com/a2",
                published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            ),
            RawAnnouncement(
                source_id="nse_official",
                headline="Market update item three",
                url="https://example.com/a3",
                published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            ),
        ]

    call_counter = {"n": 0}

    async def fake_classify(_headline: str, _details: str | None, *, allow_llm: bool = True) -> ClassificationResult:
        call_counter["n"] += 1
        if allow_llm:
            return ClassificationResult(
                "other",
                0.30,
                llm_used=False,
                llm_attempted=True,
                llm_error_type="rate_limited",
                classification_path="rule_fallback_llm_error",
            )
        return ClassificationResult(
            "other",
            0.30,
            llm_used=False,
            llm_attempted=False,
            classification_path="rule_no_llm_budget",
        )

    monkeypatch.setattr(pipeline, "seed_companies", fake_seed_companies)
    monkeypatch.setattr(pipeline, "extract_details", fake_extract_details)
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok])
    monkeypatch.setattr(pipeline, "get_collector", lambda _source: collector_ok)
    monkeypatch.setattr(pipeline, "classify_announcement", fake_classify)
    monkeypatch.setattr(pipeline, "send_announcements_email", lambda _items, run_id, recipients=None: (True, None))
    monkeypatch.setattr(pipeline.settings, "EMAIL_ALERTS_HIGH_IMPACT_ONLY", False)
    monkeypatch.setattr(pipeline.settings, "ANNOUNCEMENT_LLM_MAX_CALLS_PER_RUN", 50)
    monkeypatch.setattr(pipeline.settings, "ANNOUNCEMENT_LLM_BREAKER_FAIL_THRESHOLD", 1)

    result = await pipeline.run_announcements_pipeline()
    assert result["status"] == "success"
    metrics = result["metrics"]
    assert metrics["llm_breaker_open"] is True
    assert metrics["llm_breaker_reason"] == "llm_rate_limited"
    assert metrics["llm_attempted_count"] == 1
    assert metrics["llm_fallback_failed_count"] == 1
    assert metrics["llm_skipped_breaker_count"] >= 2
    assert call_counter["n"] >= 3
