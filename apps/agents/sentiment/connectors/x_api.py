from __future__ import annotations

from datetime import datetime

from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text

settings = get_settings()


async def collect(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    env_key = source.auth_env_key or "X_API_BEARER_TOKEN"
    token = getattr(settings, env_key, "") if source.source_id == "x_search_api" else ""
    if source.requires_auth and not token:
        return []

    headers = {"User-Agent": settings.USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "query": "NSE OR Safaricom OR KCB OR Equity",
        "max_results": 20,
    }

    result = await fetch_text(
        url=source.base_url,
        timeout_secs=source.timeout_secs,
        retries=source.retries,
        backoff_base=source.backoff_base,
        rate_limit_rps=source.rate_limit_rps,
        headers=headers,
        params=params,
    )
    if not result.ok:
        if result.status_code in (401, 403):
            return []
        raise RuntimeError(f"{result.error_type or 'fetch_error'}: {result.error or 'failed'}")
    try:
        import json

        payload = json.loads(result.text)
    except Exception as exc:  # noqa: PERF203
        raise RuntimeError(f"parse_error: {exc}") from exc

    now = utc_now()
    data = payload.get("data", []) if isinstance(payload, dict) else []
    out: list[RawPost] = []
    for item in data:
        text = normalize_text(item.get("text"))
        if not text:
            continue
        url = None
        if item.get("id"):
            url = f"https://x.com/i/web/status/{item['id']}"
        out.append(
            RawPost(
                source_id=source.source_id,
                url=url,
                canonical_url=canonicalize_url(url),
                author=None,
                title=None,
                content=text,
                published_at=None,
                fetched_at=now,
                raw_payload=item if isinstance(item, dict) else None,
            )
        )

    return out
