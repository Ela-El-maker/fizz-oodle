from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from apps.agents.sentiment import pipeline
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core import database as db
from apps.core.database import Base, get_session


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
                "TRUNCATE TABLE sentiment_digest_reports, sentiment_weekly, sentiment_ticker_mentions, "
                "sentiment_raw_posts, source_health, agent_runs, companies RESTART IDENTITY CASCADE"
            )
        )


def _source(source_id: str) -> SentimentSourceConfig:
    return SentimentSourceConfig(
        source_id=source_id,
        type="rss",
        base_url="https://example.com/.rss",
        enabled_by_default=True,
        parser="rss_news.collect",
        timeout_secs=20,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.5,
        weight=1.0,
        requires_auth=False,
    )


def _post(source_id: str, url: str, title: str, content: str) -> RawPost:
    return RawPost(
        source_id=source_id,
        url=url,
        canonical_url=url,
        author="tester",
        title=title,
        content=content,
        published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        raw_payload={"title": title},
    )


@pytest.mark.asyncio
async def test_agent_c_e2e_idempotent_partial_and_email_failure(monkeypatch) -> None:
    if not await _db_ready():
        pytest.skip("Postgres not available for e2e")

    await _reset_db()

    async def fake_seed_companies():
        return None

    source_ok = _source("standard_business_rss")
    source_bad = _source("google_news_ke_dividends")

    async def collector_ok(_source, _from_dt, _to_dt):
        return [
            _post(
                source_id="standard_business_rss",
                url="https://example.com/post-1",
                title="Safaricom outlook",
                content="Safaricom is bullish with strong results and growth",
            )
        ]

    async def collector_ok_new(_source, _from_dt, _to_dt):
        return [
            _post(
                source_id="standard_business_rss",
                url="https://example.com/post-2",
                title="KCB board outlook",
                content="KCB could see upside after strong results",
            )
        ]

    async def collector_bad(_source, _from_dt, _to_dt):
        raise RuntimeError("rss unavailable")

    monkeypatch.setattr(pipeline, "seed_companies", fake_seed_companies)

    # 1) Happy path.
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok])
    monkeypatch.setattr(pipeline, "get_collector", lambda _source: collector_ok)
    monkeypatch.setattr(pipeline, "send_digest_email", lambda **_kwargs: (True, None))
    monkeypatch.setattr(pipeline.settings, "LLM_MODE", "off")

    result_1 = await pipeline.run_sentiment_pipeline()
    assert result_1["status"] == "success"

    async with get_session() as session:
        raw_count = (await session.execute(text("SELECT COUNT(*) FROM sentiment_raw_posts"))).scalar_one()
        mention_count = (await session.execute(text("SELECT COUNT(*) FROM sentiment_ticker_mentions"))).scalar_one()
        digest_sent = (
            await session.execute(text("SELECT COUNT(*) FROM sentiment_digest_reports WHERE status='sent'"))
        ).scalar_one()
    assert raw_count == 1
    assert mention_count >= 1
    assert digest_sent == 1

    # 2) Rerun idempotency.
    result_2 = await pipeline.run_sentiment_pipeline()
    assert result_2["status"] == "success"
    assert result_2["records_new"] == 0
    assert result_2["metrics"]["digest_skipped"] is True

    # 3) Partial source failure.
    def collector_mixed(source):
        return collector_bad if source.source_id == "business_daily_rss" else collector_ok

    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok, source_bad])
    monkeypatch.setattr(pipeline, "get_collector", collector_mixed)
    result_3 = await pipeline.run_sentiment_pipeline()
    assert result_3["status"] == "partial"
    assert "error" in result_3["metrics"]["sources"]["google_news_ke_dividends"]
    assert "standard_business_rss" in result_3["metrics"]["sources"]

    # 4) Email failure leaves artifact unsent and run fails.
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_ok])
    monkeypatch.setattr(pipeline, "get_collector", lambda _source: collector_ok_new)
    monkeypatch.setattr(pipeline, "send_digest_email", lambda **_kwargs: (False, "smtp_down"))

    result_4 = await pipeline.run_sentiment_pipeline(force_send=True)
    assert result_4["status"] == "fail"
    assert result_4["metrics"]["digest_sent"] is False

    async with get_session() as session:
        digest_error = (
            await session.execute(
                text("SELECT email_error FROM sentiment_digest_reports ORDER BY week_start DESC LIMIT 1")
            )
        ).scalar_one()
    assert digest_error == "smtp_down"

    # 5) Breaker opens after repeated failures.
    monkeypatch.setattr(pipeline.settings, "SOURCE_FAIL_THRESHOLD", 2)
    monkeypatch.setattr(pipeline.settings, "SOURCE_COOLDOWN_MINUTES", 30)
    monkeypatch.setattr(pipeline, "get_source_configs", lambda: [source_bad])
    monkeypatch.setattr(pipeline, "get_collector", lambda _source: collector_bad)
    await pipeline.run_sentiment_pipeline(force_send=True)
    await pipeline.run_sentiment_pipeline(force_send=True)

    async with get_session() as session:
        breaker = (
            await session.execute(
                text("SELECT breaker_state FROM source_health WHERE source_id='google_news_ke_dividends'")
            )
        ).scalar_one()
    assert breaker == "open"
