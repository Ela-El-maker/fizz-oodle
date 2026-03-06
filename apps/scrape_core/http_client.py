from __future__ import annotations

import time as _time
from dataclasses import dataclass
from urllib.parse import urlparse
import asyncio

import httpx

from apps.scrape_core.cache_state import global_fetch_cache
from apps.scrape_core.rate_limit import global_rate_limiter
from apps.scrape_core.retry import backoff_with_jitter, classify_error_type, should_retry
from apps.scrape_core.source_health import get_source_health_tracker


@dataclass(slots=True)
class FetchResult:
    ok: bool
    text: str = ""
    status_code: int | None = None
    error_type: str | None = None
    error: str | None = None
    not_modified: bool = False
    cache_hit: bool = False
    not_modified_count: int = 0


def create_http_client(*, timeout_seconds: float, max_connections: int = 200, max_keepalive_connections: int = 40) -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_keepalive_connections)
    timeout = httpx.Timeout(timeout_seconds)
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True, limits=limits)


async def fetch_text(
    *,
    url: str,
    timeout_secs: int,
    retries: int,
    backoff_base: float,
    rate_limit_rps: float,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int | float | bool] | None = None,
    use_conditional_get: bool = False,
    cache_ttl_seconds: int = 0,
    client: httpx.AsyncClient | None = None,
    domain_key: str | None = None,
) -> FetchResult:
    domain = (domain_key or urlparse(url).netloc or "default").lower()
    req_headers = dict(headers or {})
    health_tracker = get_source_health_tracker()

    # Adaptive rate: slow down for unhealthy sources
    effective_rps = rate_limit_rps
    source_score = health_tracker.health(domain).score
    if source_score < 0.3:
        effective_rps = max(0.1, rate_limit_rps * 0.25)
    elif source_score < 0.7:
        effective_rps = max(0.1, rate_limit_rps * 0.5)

    cache_key = url
    if use_conditional_get:
        req_headers.update(global_fetch_cache.conditional_headers(cache_key, ttl_seconds=cache_ttl_seconds))

    own_client = client is None
    http_client = client or create_http_client(timeout_seconds=float(timeout_secs))

    try:
        for attempt in range(max(0, retries) + 1):
            await global_rate_limiter.acquire(domain, effective_rps)
            t0 = _time.monotonic()
            try:
                resp = await http_client.get(url, headers=req_headers, params=params)
                latency_ms = (_time.monotonic() - t0) * 1000
                status_code = int(resp.status_code)
                if status_code == 304:
                    global_rate_limiter.record_response(domain, status_code=status_code)
                    health_tracker.record(domain, ok=True, latency_ms=latency_ms)
                    not_modified_count = global_fetch_cache.record_not_modified(cache_key)
                    return FetchResult(
                        ok=True,
                        text="",
                        status_code=status_code,
                        not_modified=True,
                        cache_hit=True,
                        not_modified_count=not_modified_count,
                    )

                resp.raise_for_status()
                global_rate_limiter.record_response(domain, status_code=status_code)
                health_tracker.record(domain, ok=True, latency_ms=latency_ms)
                if use_conditional_get:
                    global_fetch_cache.record_response(
                        cache_key,
                        etag=resp.headers.get("ETag"),
                        last_modified=resp.headers.get("Last-Modified"),
                    )
                return FetchResult(ok=True, text=resp.text, status_code=status_code)
            except Exception as exc:  # noqa: PERF203
                latency_ms = (_time.monotonic() - t0) * 1000
                status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                error_type = classify_error_type(exc, status_code=status_code)
                global_rate_limiter.record_response(domain, status_code=status_code, error_type=error_type)
                health_tracker.record(domain, ok=False, latency_ms=latency_ms, error_type=error_type)
                if not should_retry(error_type, attempt, retries):
                    return FetchResult(
                        ok=False,
                        status_code=status_code,
                        error_type=error_type,
                        error=str(exc),
                    )
                await asyncio.sleep(backoff_with_jitter(backoff_base, attempt))

        return FetchResult(ok=False, error_type="unknown_error", error="exhausted")
    finally:
        if own_client:
            await http_client.aclose()
