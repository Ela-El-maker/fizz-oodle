from __future__ import annotations

from datetime import datetime, timezone

from apps.agents.announcements.sources.common import fetch_with_retries
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.core.config import get_settings
from apps.scrape_core.sitemap import collect_sitemap_urls, infer_headline_from_url

settings = get_settings()


async def collect(source: SourceConfig) -> list[RawAnnouncement]:
    max_items = min(
        max(1, int(settings.ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE)),
        max(1, int(source.max_items_per_run)),
        max(1, int(settings.SITEMAP_MAX_URLS_PER_SOURCE)),
    )

    async def _fetch(url: str) -> str:
        return await fetch_with_retries(source, url)

    rows = await collect_sitemap_urls(
        root_url=source.base_url,
        fetch_xml=_fetch,
        max_urls=max_items,
        lookback_hours=max(1, int(settings.SITEMAP_LOOKBACK_HOURS)),
    )

    out: list[RawAnnouncement] = []
    now = datetime.now(timezone.utc)
    for item in rows:
        headline = infer_headline_from_url(item.url)
        if len(headline) < 10:
            continue
        published_at = item.lastmod or now
        out.append(
            RawAnnouncement(
                source_id=source.source_id,
                headline=headline,
                url=item.url,
                published_at=published_at,
                extra={
                    "lastmod": item.lastmod.isoformat() if item.lastmod else None,
                    "sitemap_source": item.source_sitemap,
                },
            )
        )
        if len(out) >= max_items:
            break

    return out
