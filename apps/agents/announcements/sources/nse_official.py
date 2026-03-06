from __future__ import annotations

from apps.agents.announcements.sources.common import fetch_with_retries, parse_html_anchors
from apps.agents.announcements.types import RawAnnouncement, SourceConfig


async def collect(source: SourceConfig) -> list[RawAnnouncement]:
    html = await fetch_with_retries(source, source.base_url)
    return parse_html_anchors(source, html)
