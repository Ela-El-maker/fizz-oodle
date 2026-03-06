from __future__ import annotations

from random import uniform

import httpx


def classify_error_type(exc: Exception, status_code: int | None = None) -> str:
    if status_code is not None:
        if status_code in {401, 403}:
            return "blocked"
        if status_code == 429:
            return "rate_limited"
        if status_code >= 500:
            return "upstream_5xx"
        return "http_error"

    if isinstance(exc, (httpx.ReadTimeout, httpx.TimeoutException)):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        msg = str(exc).lower()
        if "name or service not known" in msg or "nodename nor servname provided" in msg:
            return "dns_error"
        return "connection_error"
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_error_type(exc, status_code=exc.response.status_code)
    return "unknown_error"


def should_retry(error_type: str, attempt: int, max_retries: int) -> bool:
    if attempt >= max_retries:
        return False
    # Never burst retry hard-policy blocks.
    if error_type in {"blocked", "missing_key", "parse_error"}:
        return False
    return True


def backoff_with_jitter(base: float, attempt: int, *, min_jitter: float = 0.05, max_jitter: float = 0.35) -> float:
    exp = max(1.0, float(base)) ** max(0, attempt)
    return exp + uniform(min_jitter, max_jitter)
