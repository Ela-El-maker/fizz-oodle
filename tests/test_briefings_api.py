from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routers import briefings as briefings_router
from apps.api.routers import fx as fx_router
from apps.api.routers import indexes as indexes_router
from apps.api.routers import prices as prices_router

client = TestClient(app)


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class SequencedSession:
    def __init__(self, results):
        self._results = list(results)

    async def execute(self, _stmt):
        if not self._results:
            raise AssertionError("No fake result prepared for execute call")
        return self._results.pop(0)


def test_briefings_latest_and_daily(monkeypatch) -> None:
    row = SimpleNamespace(
        briefing_date=date(2026, 3, 1),
        generated_at=datetime.now(timezone.utc),
        status="sent",
        subject="Daily Briefing",
        html_content="<html/>",
        metrics={
            "coverage": {"captured_tickers": 2},
            "human_summary": {"headline": "Market mood steady"},
            "executive_digest_subject": "Market Intel Daily",
            "executive_digest_sent": True,
            "executive_digest_sent_at": datetime.now(timezone.utc).isoformat(),
            "executive_digest_story_count": 6,
            "executive_digest_sections": ["one_minute", "inside_kenya"],
        },
        email_sent_at=datetime.now(timezone.utc),
        email_error=None,
        payload_hash="abc123",
    )

    @asynccontextmanager
    async def fake_get_session():
        yield SequencedSession([FakeResult([row])])

    monkeypatch.setattr(briefings_router, "get_session", fake_get_session)
    resp_latest = client.get("/briefings/latest", headers={"x-api-key": "change-me"})
    assert resp_latest.status_code == 200
    assert resp_latest.json()["item"]["status"] == "sent"
    assert resp_latest.json()["item"]["human_summary"]["headline"] == "Market mood steady"

    @asynccontextmanager
    async def fake_get_session_daily():
        yield SequencedSession([FakeResult([row])])

    monkeypatch.setattr(briefings_router, "get_session", fake_get_session_daily)
    resp_daily = client.get("/briefings/daily?date=2026-03-01", headers={"x-api-key": "change-me"})
    assert resp_daily.status_code == 200
    assert resp_daily.json()["item"]["briefing_date"] == "2026-03-01"

    @asynccontextmanager
    async def fake_get_session_exec():
        yield SequencedSession([FakeResult([row])])

    monkeypatch.setattr(briefings_router, "get_session", fake_get_session_exec)
    resp_exec = client.get("/internal/email/executive/latest", headers={"x-api-key": "change-me"})
    assert resp_exec.status_code == 200
    assert resp_exec.json()["item"]["executive_digest_sent"] is True
    assert resp_exec.json()["item"]["executive_digest_story_count"] == 6


def test_prices_fx_index_daily_routes(monkeypatch) -> None:
    price_row = SimpleNamespace(
        date=date(2026, 3, 1),
        ticker="SCOM",
        close=Decimal("19.5000"),
        open=Decimal("19.0000"),
        high=Decimal("19.9000"),
        low=Decimal("18.8000"),
        volume=Decimal("100000.000"),
        currency="KES",
        source_id="mystocks",
    )
    fx_row = SimpleNamespace(pair="KES/USD", rate=Decimal("0.007700"), source_id="erapi")
    index_row = SimpleNamespace(
        index_name="NASI",
        value=Decimal("110.2000"),
        change_val=Decimal("0.5000"),
        pct_change=Decimal("0.450"),
        source_id="mystocks",
    )

    @asynccontextmanager
    async def fake_prices_session():
        yield SequencedSession([FakeResult([price_row])])

    monkeypatch.setattr(prices_router, "get_session", fake_prices_session)
    resp_prices_daily = client.get("/prices/daily?date=2026-03-01", headers={"x-api-key": "change-me"})
    assert resp_prices_daily.status_code == 200
    assert resp_prices_daily.json()["items"][0]["ticker"] == "SCOM"

    @asynccontextmanager
    async def fake_prices_ticker_session():
        yield SequencedSession([FakeResult([price_row])])

    monkeypatch.setattr(prices_router, "get_session", fake_prices_ticker_session)
    resp_prices_ticker = client.get("/prices/SCOM?from=2026-02-20&to=2026-03-01", headers={"x-api-key": "change-me"})
    assert resp_prices_ticker.status_code == 200
    assert resp_prices_ticker.json()["ticker"] == "SCOM"

    @asynccontextmanager
    async def fake_fx_session():
        yield SequencedSession([FakeResult([fx_row])])

    monkeypatch.setattr(fx_router, "get_session", fake_fx_session)
    resp_fx = client.get("/fx/daily?date=2026-03-01", headers={"x-api-key": "change-me"})
    assert resp_fx.status_code == 200
    assert resp_fx.json()["items"][0]["pair"] == "KES/USD"

    @asynccontextmanager
    async def fake_index_session():
        yield SequencedSession([FakeResult([index_row])])

    monkeypatch.setattr(indexes_router, "get_session", fake_index_session)
    resp_index = client.get("/index/daily?date=2026-03-01", headers={"x-api-key": "change-me"})
    assert resp_index.status_code == 200
    assert resp_index.json()["items"][0]["index_name"] == "NASI"


def test_universe_summary_route(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "universe.yml"
    config_path.write_text(
        """
tracked_companies:
  - ticker: SCOM
    name: Safaricom PLC
    exchange: NSE
    sector: telecom
  - ticker: KCB
    name: KCB Group
    exchange: NSE
    sector: banking
  - ticker: MTN
    name: MTN Group
    exchange: JSE
    sector: telecom
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(prices_router.settings, "UNIVERSE_CONFIG_PATH", str(config_path))

    resp = client.get("/universe/summary", headers={"x-api-key": "change-me"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["tracked_companies"] == 3
    assert payload["tracked_tickers"] == 3
    assert payload["nse_tickers"] == 2
    assert payload["exchanges"]["NSE"] == 2
