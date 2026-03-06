from __future__ import annotations

from datetime import datetime

from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text
from apps.scrape_core.sitemap import collect_sitemap_urls, infer_headline_from_url

settings = get_settings()


async def collect(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    max_items = min(
        max(1, int(source.max_items_per_run)),
        max(1, int(settings.SITEMAP_MAX_URLS_PER_SOURCE)),
    )

    async def _fetch_xml(url: str) -> str:
        result = await fetch_text(
            url=url,
            timeout_secs=source.timeout_secs,
            retries=source.retries,
            backoff_base=source.backoff_base,
            rate_limit_rps=source.rate_limit_rps,
            headers={"User-Agent": settings.USER_AGENT},
            use_conditional_get=source.use_conditional_get,
            cache_ttl_seconds=source.cache_ttl_seconds,
        )
        if not result.ok:
            raise RuntimeError(f"{result.error_type or 'fetch_error'}: {result.error or 'failed'}")
        if result.not_modified:
            return ""
        return result.text

    entries = await collect_sitemap_urls(
        root_url=source.base_url,
        fetch_xml=_fetch_xml,
        max_urls=max_items,
        lookback_hours=max(1, int(settings.SITEMAP_LOOKBACK_HOURS)),
    )

    now = utc_now()
    out: list[RawPost] = []
    for entry in entries:
        event_dt = entry.lastmod or now
        if event_dt < from_dt or event_dt > to_dt:
            continue

        title = normalize_text(infer_headline_from_url(entry.url))
        if len(title) < 8:
            continue

        out.append(
            RawPost(
                source_id=source.source_id,
                url=entry.url,
                canonical_url=canonicalize_url(entry.url, base_url=source.base_url),
                author=None,
                title=title,
                content=title,
                published_at=entry.lastmod,
                fetched_at=now,
                raw_payload={
                    "platform": "sitemap",
                    "sitemap_source": entry.source_sitemap,
                    "lastmod": entry.lastmod.isoformat() if entry.lastmod else None,
                },
            )
        )
        if len(out) >= max_items:
            break

    return out
