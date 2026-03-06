from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.agents.sentiment.types import SentimentSourceConfig
from apps.api.main import app
from apps.api.routers import sentiment as sentiment_legacy_router
from apps.api.routers import sentiment_v2 as sentiment_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class SequencedSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No fake result prepared for execute call")
        return self._results.pop(0)


def _weekly_row() -> SimpleNamespace:
    return SimpleNamespace(
        week_start=date(2026, 3, 2),
        ticker="SCOM",
        company_name="Safaricom",
        mentions_count=10,
        bullish_count=6,
        bearish_count=2,
        neutral_count=2,
        bullish_pct=Decimal("60.00"),
        bearish_pct=Decimal("20.00"),
        neutral_pct=Decimal("20.00"),
        weighted_score=Decimal("0.300"),
        confidence=Decimal("0.810"),
        top_sources={"reddit_rss": 7},
        notable_quotes=[{"excerpt": "Strong growth", "url": "https://x"}],
        wow_delta=Decimal("0.100"),
        generated_at=datetime.now(timezone.utc),
    )


def test_sentiment_weekly_and_digest_latest(monkeypatch) -> None:
    row = _weekly_row()
    digest = SimpleNamespace(
        week_start=date(2026, 3, 2),
        generated_at=datetime.now(timezone.utc),
        status="sent",
        subject="Weekly Digest",
        html_content="<html/>",
        html_path=None,
        metrics={"mentions_created": 20},
        email_sent_at=datetime.now(timezone.utc),
        email_error=None,
        payload_hash="abc123",
    )

    @asynccontextmanager
    async def fake_session_weekly():
        yield SequencedSession(
            [
                FakeResult(scalar=date(2026, 3, 2)),
                FakeResult(scalar=1),
                FakeResult(rows=[row]),
            ]
        )

    monkeypatch.setattr(sentiment_router, "get_session", fake_session_weekly)
    resp_weekly = client.get("/sentiment/weekly", headers={"x-api-key": "change-me"})
    assert resp_weekly.status_code == 200
    assert resp_weekly.json()["items"][0]["ticker"] == "SCOM"

    @asynccontextmanager
    async def fake_session_digest():
        yield SequencedSession([FakeResult(rows=[digest])])

    monkeypatch.setattr(sentiment_router, "get_session", fake_session_digest)
    resp_digest = client.get("/sentiment/digest/latest", headers={"x-api-key": "change-me"})
    assert resp_digest.status_code == 200
    assert resp_digest.json()["item"]["status"] == "sent"


def test_sentiment_raw_and_sources_health(monkeypatch) -> None:
    mention = SimpleNamespace(
        post_id="p1",
        ticker="SCOM",
        company_name="Safaricom",
        sentiment_label="bullish",
        sentiment_score=Decimal("0.500"),
        confidence=Decimal("0.700"),
        source_weight=Decimal("1.000"),
        reasons={"bull_hits": 2},
        model_version="sentiment_rules_v1",
        llm_used=False,
        scored_at=datetime.now(timezone.utc),
    )
    raw = SimpleNamespace(
        source_id="reddit_rss",
        url="https://reddit.com/x",
        canonical_url="https://reddit.com/x",
        title="Safaricom",
        content="Bullish growth",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
    )
    health = SimpleNamespace(
        source_id="reddit_rss",
        last_success_at=datetime.now(timezone.utc),
        last_failure_at=None,
        consecutive_failures=0,
        breaker_state="closed",
        cooldown_until=None,
        last_metrics={"posts_found": 1},
    )

    @asynccontextmanager
    async def fake_session_raw():
        yield SequencedSession([FakeResult(scalar=1), FakeResult(rows=[(mention, raw)])])

    monkeypatch.setattr(sentiment_router, "get_session", fake_session_raw)
    resp_raw = client.get("/sentiment/raw", headers={"x-api-key": "change-me"})
    assert resp_raw.status_code == 200
    assert resp_raw.json()["items"][0]["ticker"] == "SCOM"

    cfg = SentimentSourceConfig(
        source_id="reddit_rss",
        type="rss",
        base_url="https://reddit.com/.rss",
        enabled_by_default=True,
        parser="reddit_rss.collect",
        timeout_secs=30,
        retries=3,
        backoff_base=2.0,
        rate_limit_rps=0.5,
        weight=1.0,
        requires_auth=False,
    )

    @asynccontextmanager
    async def fake_session_health():
        yield SequencedSession([FakeResult(rows=[health])])

    monkeypatch.setattr(sentiment_router, "get_session", fake_session_health)
    monkeypatch.setattr(sentiment_router, "get_source_configs", lambda: [cfg])
    monkeypatch.setattr(sentiment_router, "get_all_source_configs", lambda: [cfg])
    resp_health = client.get("/sentiment/sources/health", headers={"x-api-key": "change-me"})
    assert resp_health.status_code == 200
    assert resp_health.json()["items"][0]["source_id"] == "reddit_rss"


def test_legacy_v1_sentiment_latest_reads_stage4_table(monkeypatch) -> None:
    row = _weekly_row()

    @asynccontextmanager
    async def fake_session():
        yield SequencedSession([FakeResult(scalar=date(2026, 3, 2)), FakeResult(rows=[row])])

    monkeypatch.setattr(sentiment_legacy_router, "get_session", fake_session)

    resp = client.get("/v1/sentiment/latest", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["week_start"] == "2026-03-02"
    assert body["items"][0]["ticker"] == "SCOM"


def test_sentiment_themes_weekly_endpoint(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_session():
        yield SequencedSession(
            [
                FakeResult(rows=[]),
                FakeResult(rows=[]),
            ]
        )

    monkeypatch.setattr(sentiment_router, "get_session", fake_session)

    resp = client.get("/sentiment/themes/weekly?week_start=2026-03-02", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["week_start"] == "2026-03-02"
    assert body["items"] == []
