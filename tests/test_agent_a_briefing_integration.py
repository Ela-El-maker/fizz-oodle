from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from apps.agents.briefing import pipeline
from apps.agents.briefing.types import (
    ForexSnapshot,
    FxPoint,
    HeadlinePoint,
    IndexPoint,
    MarketBrief,
    PricePoint,
    PriceSnapshotNormalized,
)
from apps.core import database as db
from apps.core.chart_builder_agent_a import ChartRenderResult
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
                "TRUNCATE TABLE "
                "daily_briefings, prices_daily, index_daily, fx_daily, news_headlines_daily, "
                "agent_runs, companies RESTART IDENTITY CASCADE"
            )
        )


@pytest.mark.asyncio
async def test_agent_a_e2e_idempotent_resend_policy_and_partial(monkeypatch) -> None:
    if not await _db_ready():
        pytest.skip("Postgres not available for e2e")

    await _reset_db()

    today = date(2026, 3, 1)
    now = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    sent_subjects: list[str] = []

    class _SendResult:
        mode = "sent"
        provider = "smtp"

    class FakeEmailService:
        def send(self, subject: str, html: str, recipients=None):
            sent_subjects.append(subject)
            return _SendResult()

    async def fake_seed_companies():
        async with get_session() as session:
            await session.execute(
                text(
                    "INSERT INTO companies (ticker, name, exchange, is_active, created_at) "
                    "VALUES ('SCOM', 'Safaricom', 'NSE', true, now()), ('KCB', 'KCB Group', 'NSE', true, now()) "
                    "ON CONFLICT (ticker) DO NOTHING"
                )
            )
            await session.commit()

    def fake_universe():
        return [
            {"ticker": "SCOM", "company_name": "Safaricom", "exchange": "NSE", "aliases": ["Safaricom", "SCOM"]},
            {"ticker": "KCB", "company_name": "KCB Group", "exchange": "NSE", "aliases": ["KCB"]},
        ]

    async def fake_prices_resilient(*_args, **_kwargs):
        points = [
            PricePoint(today, "SCOM", 19.5, 19.0, 19.9, 18.8, 100000.0, "KES", "mystocks", now, {"p": 1}),
            PricePoint(today, "KCB", 21.2, 20.5, 21.5, 20.3, 85000.0, "KES", "mystocks", now, {"p": 2}),
        ]
        normalized = [
            PriceSnapshotNormalized(
                date=today,
                ticker="SCOM",
                exchange="NSE",
                close=19.5,
                prev_close=19.0,
                open=19.0,
                high=19.9,
                low=18.8,
                volume=100000.0,
                pct_change=2.63,
                direction="up",
                source_id="mystocks",
                source_priority=2,
                source_confidence=0.8,
                status="ok",
                error_type=None,
                error=None,
                fetched_at=now,
                raw_payload={"p": 1},
            ),
            PriceSnapshotNormalized(
                date=today,
                ticker="KCB",
                exchange="NSE",
                close=21.2,
                prev_close=20.5,
                open=20.5,
                high=21.5,
                low=20.3,
                volume=85000.0,
                pct_change=3.41,
                direction="up",
                source_id="mystocks",
                source_priority=2,
                source_confidence=0.8,
                status="ok",
                error_type=None,
                error=None,
                fetched_at=now,
                raw_payload={"p": 2},
            ),
        ]
        diag = {
            "source_stats": {
                "mystocks": {"attempted": 2, "success": 2, "failed": 0},
                "alpha_vantage": {"attempted": 2, "success": 0, "failed": 2},
            },
            "missing_tickers": [],
            "ticker_failures": {
                "SCOM": [{"source_id": "alpha_vantage", "error_type": "rate_limited", "error": "429"}],
                "KCB": [{"source_id": "alpha_vantage", "error_type": "rate_limited", "error": "429"}],
            },
        }
        return points, normalized, diag

    async def fake_index(_target_date):
        return [IndexPoint(today, "NASI", 110.2, 0.5, 0.45, "mystocks", now, {"i": 1})], {
            "source_used": "mystocks",
            "status": "fresh",
            "error": None,
        }

    async def fake_fx(_session, _target_date):
        return [
            FxPoint(today, "KES/USD", 0.0077, "erapi", now, {"f": 1}),
            FxPoint(today, "KES/EUR", 0.0071, "erapi", now, {"f": 2}),
        ], [
            ForexSnapshot(today, "KES/USD", 0.0077, "erapi", "fresh", 0.0, 0.95, now, {}),
            ForexSnapshot(today, "KES/EUR", 0.0071, "erapi", "fresh", 0.0, 0.95, now, {}),
        ], {
            "source_used": "erapi",
            "status": "fresh",
            "error": None,
            "pairs": {"KES/USD": {"status": "fresh"}, "KES/EUR": {"status": "fresh"}},
        }

    async def fake_news(*_args, **_kwargs):
        return [HeadlinePoint(today, "mystocks_news", "Safaricom posts strong growth", "https://example.com/n1", None, now)], {
            "sources": {"mystocks_news": {"status": "success", "count": 1}},
            "rows_before_filter": 1,
            "rows_after_filter": 1,
        }

    async def fake_brief(_context):
        brief = MarketBrief(
            market_pulse="Market tone constructive",
            drivers=["Breadth", "Index move"],
            unusual_signals=["None"],
            narrative_interpretation="Risk-on bias visible.",
            confidence_level="medium",
            confidence_score=0.7,
            confidence_reason="rule_mix",
            model="unit-test",
            provider="test",
            llm_used=False,
            llm_error="llm_disabled",
        )
        return brief, "Deterministic test summary"

    monkeypatch.setattr(pipeline, "_briefing_date_eat", lambda: today)
    monkeypatch.setattr(pipeline, "_tracked_universe", fake_universe)
    monkeypatch.setattr(pipeline, "seed_companies", fake_seed_companies)
    monkeypatch.setattr(pipeline, "fetch_prices_resilient", fake_prices_resilient)
    monkeypatch.setattr(pipeline, "fetch_index_nasi_resilient", fake_index)
    monkeypatch.setattr(pipeline, "_load_fx_with_fallback", fake_fx)
    monkeypatch.setattr(pipeline, "_collect_news", fake_news)
    monkeypatch.setattr(pipeline, "generate_market_brief", fake_brief)
    monkeypatch.setattr(
        pipeline,
        "build_agent_a_top_movers_chart",
        lambda **_kwargs: ChartRenderResult(generated=True, b64_png="chart", path="/tmp/chart.png", error=None),
    )
    monkeypatch.setattr(pipeline, "EmailService", FakeEmailService)
    monkeypatch.setattr(pipeline.settings, "DAILY_BRIEFING_FORCE_SEND", False)
    monkeypatch.setattr(pipeline.settings, "EMAIL_EXEC_DIGEST_ENABLED", True)
    monkeypatch.setattr(pipeline.settings, "EMAIL_EXEC_DIGEST_PARALLEL_LEGACY", False)

    # 1) happy path writes rows and sends one email
    result_1 = await pipeline.run_daily_briefing_pipeline()
    assert result_1["status"] == "success"
    assert len(sent_subjects) == 1

    async with get_session() as session:
        prices_count = (await session.execute(text("SELECT COUNT(*) FROM prices_daily WHERE date='2026-03-01'"))).scalar_one()
        briefings_count = (await session.execute(text("SELECT COUNT(*) FROM daily_briefings WHERE briefing_date='2026-03-01'"))).scalar_one()
    assert prices_count == 2
    assert briefings_count == 1

    # 2) rerun same date should not resend when already sent and force=false
    result_2 = await pipeline.run_daily_briefing_pipeline()
    assert result_2["status"] == "success"
    assert result_2["metrics"]["email_skipped"] is True
    assert len(sent_subjects) == 1

    # 3) partial source failure still produces briefing artifact and partial status
    async def failing_index(_target_date):
        return [], {"source_used": None, "status": "missing", "error": "index_source_down"}

    monkeypatch.setattr(pipeline, "fetch_index_nasi_resilient", failing_index)
    result_3 = await pipeline.run_daily_briefing_pipeline()
    assert result_3["status"] == "partial"
    assert "index" in result_3["metrics"]["channel_errors"]

    # 4) force send bypasses existing sent-at guard
    monkeypatch.setattr(pipeline, "fetch_index_nasi_resilient", fake_index)
    result_4 = await pipeline.run_daily_briefing_pipeline(force_send=True)
    assert result_4["status"] == "success"
    assert result_4["metrics"]["channels"]["index"]["source_used"] == "mystocks"
    assert result_4["metrics"]["channels"]["index"]["status"] == "fresh"
    assert len(sent_subjects) == 2
