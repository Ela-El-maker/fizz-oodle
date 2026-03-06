from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from apps.agents.analyst import pipeline
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
                "TRUNCATE TABLE analyst_reports, agent_runs, daily_briefings, announcements, "
                "sentiment_weekly, sentiment_digest_reports, prices_daily, index_daily, fx_daily "
                "RESTART IDENTITY CASCADE"
            )
        )


async def _seed_upstream() -> None:
    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO daily_briefings "
                "(briefing_date, generated_at, status, subject, html_content, metrics, email_sent_at, payload_hash) "
                "VALUES ('2026-03-01', now(), 'sent', 'Briefing', '<p>briefing</p>', '{}'::jsonb, now(), 'hashb')"
            )
        )

        await session.execute(
            text(
                "INSERT INTO prices_daily (date, ticker, close, currency, source_id, fetched_at) VALUES "
                "('2026-02-28', 'SCOM', 20.0, 'KES', 'mystocks', now()),"
                "('2026-03-01', 'SCOM', 21.0, 'KES', 'mystocks', now()),"
                "('2026-02-28', 'KCB', 19.5, 'KES', 'mystocks', now()),"
                "('2026-03-01', 'KCB', 18.5, 'KES', 'mystocks', now())"
            )
        )

        await session.execute(
            text(
                "INSERT INTO index_daily (date, index_name, value, change_val, pct_change, source_id, fetched_at) VALUES "
                "('2026-03-01', 'NASI', 120.2, 1.1, 0.9, 'mystocks', now())"
            )
        )

        await session.execute(
            text(
                "INSERT INTO fx_daily (date, pair, rate, source_id, fetched_at) VALUES "
                "('2026-03-01', 'KES/USD', 0.0078, 'erapi', now())"
            )
        )

        await session.execute(
            text(
                "INSERT INTO announcements "
                "(announcement_id, source_id, ticker, company, title, headline, url, canonical_url, announcement_date, "
                "announcement_type, type_confidence, first_seen_at, last_seen_at, alerted) "
                "VALUES "
                "('a-1', 'nse', 'SCOM', 'Safaricom', 'Results release', 'Results release', 'https://example.com/a-1', "
                "'https://example.com/a-1', now(), 'earnings', 0.900, now(), now(), false)"
            )
        )

        await session.execute(
            text(
                "INSERT INTO sentiment_weekly "
                "(week_start, ticker, company_name, mentions_count, bullish_count, bearish_count, neutral_count, "
                "bullish_pct, bearish_pct, neutral_pct, weighted_score, confidence, top_sources, notable_quotes, wow_delta, generated_at) "
                "VALUES "
                "('2026-02-23', 'SCOM', 'Safaricom', 10, 6, 2, 2, 60.0, 20.0, 20.0, 0.330, 0.810, "
                "'{\"reddit\": 8}'::jsonb, '[]'::jsonb, 0.100, now())"
            )
        )

        await session.execute(
            text(
                "INSERT INTO sentiment_digest_reports "
                "(week_start, generated_at, status, subject, html_content, metrics, email_sent_at, payload_hash) "
                "VALUES ('2026-02-23', now(), 'sent', 'Sentiment Digest', '<p>sent</p>', '{}'::jsonb, now(), 'hashs')"
            )
        )

        await session.commit()


@pytest.mark.asyncio
async def test_agent_d_pipeline_happy_idempotent_partial_and_email_failure(monkeypatch) -> None:
    if not await _db_ready():
        pytest.skip("Postgres not available for agent d integration")

    await _reset_db()
    await _seed_upstream()

    sent_subjects: list[str] = []

    def fake_send(subject: str, html: str):
        sent_subjects.append(subject)
        return True, None

    async def fake_polish(overview, _report_type):
        return overview, False, None

    monkeypatch.setattr(pipeline, "send_report_email", fake_send)
    monkeypatch.setattr(pipeline, "polish_overview", fake_polish)
    monkeypatch.setattr(pipeline.settings, "LLM_MODE", "off")

    # 1) happy path daily
    result_daily = await pipeline.run_analyst_pipeline(report_type="daily", period_key=date(2026, 3, 1))
    assert result_daily["status"] == "success"
    assert result_daily["metrics"]["llm_used"] is False
    assert "feedback_applied" in result_daily["metrics"]
    assert "feedback_coverage_pct" in result_daily["metrics"]
    assert "decision_trace" in result_daily["metrics"]
    assert len(sent_subjects) == 1

    # 2) happy path weekly
    result_weekly = await pipeline.run_analyst_pipeline(report_type="weekly", period_key=date(2026, 2, 23))
    assert result_weekly["status"] == "success"
    assert len(sent_subjects) == 2

    # 3) idempotent rerun should skip resend
    rerun_daily = await pipeline.run_analyst_pipeline(report_type="daily", period_key=date(2026, 3, 1))
    assert rerun_daily["status"] == "success"
    assert rerun_daily["metrics"]["email_skipped"] is True
    assert len(sent_subjects) == 2

    # 4) degraded partial run when upstream missing
    partial = await pipeline.run_analyst_pipeline(report_type="daily", period_key=date(2000, 1, 1))
    assert partial["status"] == "partial"
    assert partial["metrics"]["degraded"] is True

    # 5) email failure stores artifact with error
    def failing_send(subject: str, html: str):
        return False, "smtp_down"

    monkeypatch.setattr(pipeline, "send_report_email", failing_send)
    failed = await pipeline.run_analyst_pipeline(report_type="daily", period_key=date(2026, 3, 2), force_send=True)
    assert failed["status"] == "fail"
    assert failed["metrics"]["email_error"] == "smtp_down"

    async with get_session() as session:
        daily_count = (
            await session.execute(
                text("SELECT COUNT(*) FROM analyst_reports WHERE report_type='daily' AND period_key='2026-03-01'")
            )
        ).scalar_one()
        email_error = (
            await session.execute(
                text("SELECT email_error FROM analyst_reports WHERE report_type='daily' AND period_key='2026-03-02'")
            )
        ).scalar_one_or_none()

    assert daily_count == 1
    assert email_error == "smtp_down"
