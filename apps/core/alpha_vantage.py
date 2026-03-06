from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any

from apps.agents.briefing.normalize import parse_float
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text

settings = get_settings()

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"


def _symbol_for_ticker(ticker: str, exchange: str = "NSE") -> str:
    if exchange.upper().strip() == "NSE":
        return f"{ticker.upper().strip()}.NBO"
    return ticker.upper().strip()


def _parse_quote(payload: dict[str, Any], *, ticker: str, exchange: str) -> dict[str, Any]:
    note = str(payload.get("Note") or payload.get("Information") or "").strip()
    if note and ("frequency" in note.lower() or "rate" in note.lower()):
        raise RuntimeError(f"rate_limited: {note}")
    if payload.get("Error Message"):
        raise RuntimeError(f"parse_error: {payload.get('Error Message')}")

    quote = payload.get("Global Quote")
    if not isinstance(quote, dict) or not quote:
        raise RuntimeError("parse_error: empty_global_quote")

    close = parse_float(quote.get("05. price"))
    prev_close = parse_float(quote.get("08. previous close"))
    volume = parse_float(quote.get("06. volume"))
    pct_change = parse_float(quote.get("10. change percent"))
    if close is None:
        raise RuntimeError("parse_error: missing_price")

    if pct_change is None and prev_close not in (None, 0):
        pct_change = ((close - float(prev_close)) / float(prev_close)) * 100.0

    return {
        "ticker": ticker.upper().strip(),
        "exchange": exchange.upper().strip(),
        "close": close,
        "prev_close": prev_close,
        "pct_change": round(float(pct_change), 4) if pct_change is not None else None,
        "volume": volume,
        "source_id": "alpha_vantage",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "raw": quote,
    }


async def fetch_alpha_quote_context(
    ticker: str,
    *,
    exchange: str = "NSE",
    target_date: date | None = None,
) -> dict[str, Any]:
    api_key = (settings.ALPHA_VANTAGE_API_KEY or "").strip()
    if not api_key:
        raise RuntimeError("missing_key: ALPHA_VANTAGE_API_KEY")

    symbol = _symbol_for_ticker(ticker=ticker, exchange=exchange)
    res = await fetch_text(
        url=ALPHA_VANTAGE_URL,
        params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": api_key},
        timeout_secs=25,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=1.0 / 12.0,  # 5 req/min
        headers={"User-Agent": settings.USER_AGENT},
        use_conditional_get=False,
        cache_ttl_seconds=0,
        domain_key="alphavantage.co",
    )
    if not res.ok:
        raise RuntimeError(f"{res.error_type or 'fetch_error'}: {res.error or 'failed'}")
    try:
        payload = json.loads(res.text)
    except Exception as exc:  # noqa: PERF203
        raise RuntimeError(f"parse_error: {exc}") from exc

    out = _parse_quote(payload, ticker=ticker, exchange=exchange)
    out["target_date"] = (target_date or date.today()).isoformat()
    return out


async def fetch_alpha_quote_batch(
    tickers: list[str],
    *,
    exchange: str = "NSE",
    target_date: date | None = None,
    max_tickers: int = 5,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    ordered = []
    for ticker in tickers:
        t = str(ticker or "").upper().strip()
        if t and t not in ordered:
            ordered.append(t)
    for ticker in ordered[: max(0, int(max_tickers))]:
        try:
            result[ticker] = await fetch_alpha_quote_context(
                ticker=ticker,
                exchange=exchange,
                target_date=target_date,
            )
        except Exception as exc:  # noqa: PERF203
            errors[ticker] = str(exc)
    return result, {
        "requested": min(len(ordered), max(0, int(max_tickers))),
        "received": len(result),
        "failed": len(errors),
        "errors": errors,
    }

