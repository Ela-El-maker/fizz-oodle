from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
import json
import re
from typing import Any

from bs4 import BeautifulSoup
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from apps.agents.briefing.compute import compute_change
from apps.agents.briefing.normalize import parse_float, utc_now
from apps.agents.briefing.source_health import source_can_run
from apps.agents.briefing.sources import (
    NSE_MARKET_STATS_URL,
    _http_get,
    fetch_prices_mystocks,
)
from apps.agents.briefing.types import PricePoint, PriceSnapshotNormalized
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text
from apps.scrape_core.retry import classify_error_type

settings = get_settings()

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
_TYPED_PREFIXES = {
    "rate_limited",
    "timeout",
    "dns_error",
    "connection_error",
    "upstream_5xx",
    "blocked",
    "parse_error",
    "missing_key",
    "source_breaker_open",
}


@dataclass(slots=True)
class SourceFailure:
    source_id: str
    error_type: str
    error: str


def _direction_from_pct(pct_change: float | None) -> str:
    if pct_change is None:
        return "unknown"
    if pct_change > 0:
        return "up"
    if pct_change < 0:
        return "down"
    return "flat"


def _coerce_error_type(exc: Exception | str) -> str:
    if isinstance(exc, str):
        raw = exc
    else:
        raw = str(exc)
    prefix = raw.split(":", 1)[0].strip().lower()
    if prefix in _TYPED_PREFIXES:
        return prefix
    if isinstance(exc, Exception):
        return classify_error_type(exc)
    return "unknown_error"


def _alpha_symbol(ticker: str, exchange: str) -> str:
    ex = exchange.upper().strip()
    if ex == "NSE":
        return f"{ticker}.NBO"
    return ticker


def _parse_alpha_vantage_quote(payload: dict[str, Any], ticker: str, exchange: str, now) -> PriceSnapshotNormalized:
    if not isinstance(payload, dict):
        raise RuntimeError("parse_error: invalid_payload")
    note = str(payload.get("Note") or payload.get("Information") or "").strip()
    if note and ("frequency" in note.lower() or "rate" in note.lower()):
        raise RuntimeError(f"rate_limited: {note}")

    quote = payload.get("Global Quote")
    if not isinstance(quote, dict) or not quote:
        raise RuntimeError(f"parse_error: empty_global_quote:{ticker}")

    close = parse_float(quote.get("05. price"))
    prev_close = parse_float(quote.get("08. previous close"))
    open_price = parse_float(quote.get("02. open"))
    high = parse_float(quote.get("03. high"))
    low = parse_float(quote.get("04. low"))
    volume = parse_float(quote.get("06. volume"))

    if close is None:
        raise RuntimeError(f"parse_error: missing_price:{ticker}")

    _change, pct_change = compute_change(close, prev_close)
    return PriceSnapshotNormalized(
        date=now.date(),
        ticker=ticker,
        exchange=exchange,
        close=close,
        prev_close=prev_close,
        open=open_price,
        high=high,
        low=low,
        volume=volume,
        pct_change=pct_change,
        direction=_direction_from_pct(pct_change),
        source_id="alpha_vantage",
        source_priority=1,
        source_confidence=0.9,
        status="ok",
        error_type=None,
        error=None,
        fetched_at=now,
        raw_payload=quote,
    )


async def fetch_price_alpha_vantage(target_date: date, ticker: str, exchange: str) -> PriceSnapshotNormalized:
    api_key = (settings.ALPHA_VANTAGE_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("missing_key: ALPHA_VANTAGE_API_KEY")

    symbol = _alpha_symbol(ticker, exchange)
    res = await fetch_text(
        url=ALPHA_VANTAGE_URL,
        params={
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": api_key,
        },
        timeout_secs=25,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=1.0 / 12.0,
        headers={"User-Agent": settings.USER_AGENT},
        cache_ttl_seconds=0,
        use_conditional_get=False,
        domain_key="alphavantage.co",
    )
    if not res.ok:
        raise RuntimeError(f"{res.error_type or 'fetch_error'}: {res.error or 'failed'}")
    try:
        payload = json.loads(res.text)
    except Exception as exc:  # noqa: PERF203
        raise RuntimeError(f"parse_error: {exc}") from exc

    now = utc_now()
    parsed = _parse_alpha_vantage_quote(payload, ticker=ticker, exchange=exchange, now=now)
    parsed.date = target_date
    return parsed


async def fetch_price_mystocks_single(target_date: date, ticker: str, exchange: str) -> PriceSnapshotNormalized:
    rows = await fetch_prices_mystocks(target_date, [ticker])
    if not rows:
        raise RuntimeError(f"parse_error: mystocks_missing:{ticker}")
    row = rows[0]
    _change, pct_change = compute_change(row.close, row.open if row.open is not None else row.close)
    return PriceSnapshotNormalized(
        date=target_date,
        ticker=ticker,
        exchange=exchange,
        close=row.close,
        prev_close=row.open,
        open=row.open,
        high=row.high,
        low=row.low,
        volume=row.volume,
        pct_change=pct_change,
        direction=_direction_from_pct(pct_change),
        source_id="mystocks",
        source_priority=2,
        source_confidence=0.8,
        status="ok",
        error_type=None,
        error=None,
        fetched_at=row.fetched_at,
        raw_payload=row.raw_payload,
    )


async def fetch_price_nse_market_stats(target_date: date, ticker: str, exchange: str) -> PriceSnapshotNormalized:
    # Last-resort parser for ticker rows embedded in NSE market stats text.
    html = await _http_get(
        NSE_MARKET_STATS_URL,
        timeout=30,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.25,
        use_conditional_get=True,
        cache_ttl_seconds=300,
    )
    text = " ".join(BeautifulSoup(html, "lxml").stripped_strings)
    # Pattern examples vary heavily; treat all fields besides close as optional.
    pattern = re.compile(
        rf"\b{re.escape(ticker)}\b(?:\s+[^\d]{{0,30}})?\s+([0-9,]+(?:\.[0-9]+)?)",
        flags=re.I,
    )
    m = pattern.search(text)
    if not m:
        raise RuntimeError(f"parse_error: nse_price_missing:{ticker}")
    close = parse_float(m.group(1))
    now = utc_now()
    return PriceSnapshotNormalized(
        date=target_date,
        ticker=ticker,
        exchange=exchange,
        close=close,
        prev_close=None,
        open=None,
        high=None,
        low=None,
        volume=None,
        pct_change=None,
        direction="unknown",
        source_id="nse_market_stats_prices",
        source_priority=3,
        source_confidence=0.55,
        status="degraded",
        error_type=None,
        error=None,
        fetched_at=now,
        raw_payload={"match": m.group(0)},
    )


def _to_price_point(row: PriceSnapshotNormalized) -> PricePoint:
    return PricePoint(
        date=row.date,
        ticker=row.ticker,
        close=row.close,
        open=row.open,
        high=row.high,
        low=row.low,
        volume=row.volume,
        currency="KES",
        source_id=row.source_id,
        fetched_at=row.fetched_at,
        raw_payload=row.raw_payload,
    )


async def _resolve_single_ticker(
    *,
    target_date: date,
    ticker: str,
    exchange: str,
    source_order: list[str],
    source_allowed: dict[str, bool] | None,
) -> tuple[PriceSnapshotNormalized, list[SourceFailure]]:
    failures: list[SourceFailure] = []
    for source_id in source_order:
        if source_allowed is not None:
            allowed = bool(source_allowed.get(source_id, True))
            if not allowed:
                failures.append(
                    SourceFailure(
                        source_id=source_id,
                        error_type="source_breaker_open",
                        error="source breaker open",
                    )
                )
                continue

        try:
            if source_id == "alpha_vantage":
                return await fetch_price_alpha_vantage(target_date=target_date, ticker=ticker, exchange=exchange), failures
            if source_id == "mystocks":
                return await fetch_price_mystocks_single(target_date=target_date, ticker=ticker, exchange=exchange), failures
            if source_id == "nse_market_stats_prices":
                return await fetch_price_nse_market_stats(target_date=target_date, ticker=ticker, exchange=exchange), failures
        except Exception as exc:  # noqa: PERF203
            failures.append(SourceFailure(source_id=source_id, error_type=_coerce_error_type(exc), error=str(exc)))
            continue

    row = PriceSnapshotNormalized(
        date=target_date,
        ticker=ticker,
        exchange=exchange,
        close=None,
        prev_close=None,
        open=None,
        high=None,
        low=None,
        volume=None,
        pct_change=None,
        direction="unknown",
        source_id="none",
        source_priority=99,
        source_confidence=0.0,
        status="missing",
        error_type="all_sources_failed",
        error="all_sources_failed",
        fetched_at=utc_now(),
        raw_payload={"failed_sources": [f"{x.source_id}:{x.error_type}" for x in failures]},
    )
    return row, failures


async def fetch_prices_resilient(
    *,
    target_date: date,
    universe_rows: list[dict[str, Any]],
    source_order: list[str],
    session: AsyncSession | None = None,
) -> tuple[list[PricePoint], list[PriceSnapshotNormalized], dict[str, Any]]:
    semaphore = asyncio.Semaphore(max(1, int(settings.AGENT_A_PRICE_MAX_CONCURRENCY)))
    now_utc = utc_now()
    source_allowed: dict[str, bool] | None = None
    if session is not None:
        source_allowed = {}
        for source_id in source_order:
            source_allowed[source_id] = await source_can_run(
                session=session,
                source_id=source_id,
                breaker_enabled=settings.SOURCE_BREAKER_ENABLED,
                now_utc=now_utc,
            )

    diagnostics: dict[str, Any] = {
        "source_stats": {},
        "ticker_failures": {},
        "missing_tickers": [],
    }
    for source_id in source_order:
        diagnostics["source_stats"][source_id] = {"attempted": 0, "success": 0, "failed": 0}

    async def _one(row: dict[str, Any]) -> tuple[PriceSnapshotNormalized, list[SourceFailure]]:
        ticker = str(row.get("ticker", "")).upper().strip()
        exchange = str(row.get("exchange", "NSE")).upper().strip()
        async with semaphore:
            return await _resolve_single_ticker(
                target_date=target_date,
                ticker=ticker,
                exchange=exchange,
                source_order=source_order,
                source_allowed=source_allowed,
            )

    tasks = [_one(row) for row in universe_rows]
    resolved = await asyncio.gather(*tasks)

    normalized: list[PriceSnapshotNormalized] = []
    points: list[PricePoint] = []
    for row, failures in resolved:
        normalized.append(row)
        if row.close is not None:
            points.append(_to_price_point(row))
        else:
            diagnostics["missing_tickers"].append(row.ticker)
        if failures:
            diagnostics["ticker_failures"][row.ticker] = [
                {"source_id": f.source_id, "error_type": f.error_type, "error": f.error}
                for f in failures
            ]
        for source_id in source_order:
            stats = diagnostics["source_stats"][source_id]
            was_attempted = any(f.source_id == source_id for f in failures) or row.source_id == source_id
            if not was_attempted:
                continue
            stats["attempted"] += 1
            if row.source_id == source_id:
                stats["success"] += 1
            elif any(f.source_id == source_id for f in failures):
                stats["failed"] += 1

    return points, normalized, diagnostics
