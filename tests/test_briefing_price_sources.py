from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from apps.agents.briefing import price_sources
from apps.agents.briefing.types import PriceSnapshotNormalized


def _row(
    *,
    ticker: str,
    source_id: str,
    close: float | None = 10.0,
    status: str = "ok",
    error_type: str | None = None,
) -> PriceSnapshotNormalized:
    return PriceSnapshotNormalized(
        date=date(2026, 3, 1),
        ticker=ticker,
        exchange="NSE",
        close=close,
        prev_close=9.0,
        open=9.0,
        high=10.1,
        low=8.9,
        volume=1234.0,
        pct_change=11.11 if close is not None else None,
        direction="up" if close else "unknown",
        source_id=source_id,
        source_priority=1,
        source_confidence=0.9 if close is not None else 0.0,
        status=status,  # type: ignore[arg-type]
        error_type=error_type,
        error=error_type,
        fetched_at=datetime(2026, 3, 1, 5, 0, tzinfo=timezone.utc),
        raw_payload={"x": 1},
    )


def test_alpha_vantage_parser_maps_quote() -> None:
    payload = {
        "Global Quote": {
            "05. price": "23.11",
            "08. previous close": "22.80",
            "02. open": "22.50",
            "03. high": "23.50",
            "04. low": "22.41",
            "06. volume": "102300",
        }
    }
    row = price_sources._parse_alpha_vantage_quote(  # noqa: SLF001
        payload=payload,
        ticker="SCOM",
        exchange="NSE",
        now=datetime(2026, 3, 1, 5, 0, tzinfo=timezone.utc),
    )
    assert row.source_id == "alpha_vantage"
    assert row.close == 23.11
    assert row.prev_close == 22.8
    assert row.direction == "up"


def test_alpha_vantage_parser_detects_rate_limit_note() -> None:
    payload = {"Note": "Thank you. API call frequency is 5 calls per minute and 500 calls per day."}
    with pytest.raises(RuntimeError, match="rate_limited"):
        price_sources._parse_alpha_vantage_quote(  # noqa: SLF001
            payload=payload,
            ticker="SCOM",
            exchange="NSE",
            now=datetime(2026, 3, 1, 5, 0, tzinfo=timezone.utc),
        )


@pytest.mark.asyncio
async def test_fetch_prices_resilient_falls_back_to_mystocks(monkeypatch) -> None:
    async def fail_alpha(*_args, **_kwargs):
        raise RuntimeError("rate_limited: too_many_requests")

    async def ok_mystocks(*_args, **_kwargs):
        return _row(ticker="SCOM", source_id="mystocks", close=20.5)

    monkeypatch.setattr(price_sources, "fetch_price_alpha_vantage", fail_alpha)
    monkeypatch.setattr(price_sources, "fetch_price_mystocks_single", ok_mystocks)

    points, normalized, diag = await price_sources.fetch_prices_resilient(
        target_date=date(2026, 3, 1),
        universe_rows=[{"ticker": "SCOM", "exchange": "NSE"}],
        source_order=["alpha_vantage", "mystocks", "nse_market_stats_prices"],
        session=None,
    )

    assert len(points) == 1
    assert normalized[0].source_id == "mystocks"
    assert diag["source_stats"]["alpha_vantage"]["failed"] == 1
    assert diag["source_stats"]["mystocks"]["success"] == 1


@pytest.mark.asyncio
async def test_fetch_prices_resilient_returns_missing_when_all_fail(monkeypatch) -> None:
    async def fail_all(*_args, **_kwargs):
        raise RuntimeError("timeout: upstream_timeout")

    monkeypatch.setattr(price_sources, "fetch_price_alpha_vantage", fail_all)
    monkeypatch.setattr(price_sources, "fetch_price_mystocks_single", fail_all)
    monkeypatch.setattr(price_sources, "fetch_price_nse_market_stats", fail_all)

    points, normalized, diag = await price_sources.fetch_prices_resilient(
        target_date=date(2026, 3, 1),
        universe_rows=[{"ticker": "SCOM", "exchange": "NSE"}],
        source_order=["alpha_vantage", "mystocks", "nse_market_stats_prices"],
        session=None,
    )

    assert points == []
    assert normalized[0].status == "missing"
    assert normalized[0].error_type == "all_sources_failed"
    assert "SCOM" in diag["missing_tickers"]
