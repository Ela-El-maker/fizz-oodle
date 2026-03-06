from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.agents.sentiment.types import SentimentSourceConfig
from apps.api.main import app
from apps.api.routers import admin_sentiment as admin_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
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


def test_admin_sentiment_page_renders(monkeypatch) -> None:
    run_row = SimpleNamespace(
        run_id=uuid4(),
        status="partial",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        metrics={"sources": {"reddit_rss": {"posts_found": 2}}},
    )
    weekly_row = SimpleNamespace(
        ticker="SCOM",
        company_name="Safaricom",
        mentions_count=5,
        bullish_pct=Decimal("60.00"),
        bearish_pct=Decimal("20.00"),
        neutral_pct=Decimal("20.00"),
        weighted_score=Decimal("0.250"),
        confidence=Decimal("0.800"),
        wow_delta=Decimal("0.100"),
    )
    raw_row = SimpleNamespace(
        source_id="reddit_rss",
        title="Safaricom outlook",
        content="Strong growth",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/post",
    )
    health_row = SimpleNamespace(
        source_id="reddit_rss",
        breaker_state="closed",
        consecutive_failures=0,
        cooldown_until=None,
        last_metrics={"posts_found": 2},
    )
    digest_row = SimpleNamespace(
        week_start=date(2026, 3, 2),
        status="sent",
        email_sent_at=datetime.now(timezone.utc),
        email_error=None,
    )

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
    async def fake_get_session():
        yield SequencedSession(
            [
                FakeResult([run_row]),
                FakeResult([weekly_row]),
                FakeResult([raw_row]),
                FakeResult([health_row]),
                FakeResult([digest_row]),
            ]
        )

    monkeypatch.setattr(admin_router, "get_session", fake_get_session)
    monkeypatch.setattr(admin_router, "get_source_configs", lambda: [cfg])
    monkeypatch.setattr(admin_router, "get_all_source_configs", lambda: [cfg])

    resp = client.get("/admin/sentiment?week_start=2026-03-02&ticker=SCOM", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert "Sentiment Admin" in resp.text
    assert "Latest Agent C Run" in resp.text


def test_admin_trigger_sentiment(monkeypatch) -> None:
    run_id = str(uuid4())
    captured = {}

    async def fake_start_run(_agent_name: str):
        return run_id

    def fake_send_task(task_name: str, kwargs: dict):
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs

    monkeypatch.setattr(admin_router, "start_run", fake_start_run)
    monkeypatch.setattr(admin_router.celery_app, "send_task", fake_send_task)

    resp = client.post("/admin/sentiment/trigger", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id
    assert captured["task_name"] == "agent_sentiment.run"


def test_admin_resend_sentiment(monkeypatch) -> None:
    run_id = str(uuid4())
    captured = {}

    async def fake_start_run(_agent_name: str):
        return run_id

    def fake_send_task(task_name: str, kwargs: dict):
        captured["task_name"] = task_name
        captured["kwargs"] = kwargs

    monkeypatch.setattr(admin_router, "start_run", fake_start_run)
    monkeypatch.setattr(admin_router.celery_app, "send_task", fake_send_task)

    resp = client.post(
        "/admin/sentiment/resend?week_start=2026-03-02&force=true",
        headers={"x-api-key": "change-me"},
    )
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id
    assert captured["task_name"] == "agent_sentiment.run"
    assert captured["kwargs"]["week_start"] == "2026-03-02"
    assert captured["kwargs"]["force_send"] is True


def test_admin_reset_sentiment_source_health(monkeypatch) -> None:
    row = SimpleNamespace(
        source_id="reddit_rss",
        consecutive_failures=3,
        breaker_state="open",
        cooldown_until=datetime.now(timezone.utc),
        last_metrics={"error": "blocked"},
    )

    class ResetSession:
        def __init__(self):
            self.committed = False

        async def execute(self, _stmt):
            return FakeResult([row])

        async def commit(self):
            self.committed = True

    @asynccontextmanager
    async def fake_get_session():
        yield ResetSession()

    monkeypatch.setattr(admin_router, "get_session", fake_get_session)
    resp = client.post("/admin/sentiment/sources/reset?source_id=reddit_rss", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["reset_count"] == 1
    assert row.breaker_state == "closed"
    assert row.consecutive_failures == 0
