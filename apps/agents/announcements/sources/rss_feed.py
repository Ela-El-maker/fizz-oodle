from __future__ import annotations

from apps.agents.announcements.sources.common import fetch_with_retries, parse_rss_items
from apps.agents.announcements.types import RawAnnouncement, SourceConfig


async def collect(source: SourceConfig) -> list[RawAnnouncement]:
    # Try source URL first; if it's HTML-only the parser simply returns empty.
    body = await fetch_with_retries(source, source.base_url)
    return parse_rss_items(source, body)
