from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from apps.agents.announcements.sources.common import fetch_with_retries
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.core.config import get_settings

settings = get_settings()

_KEYWORDS = re.compile(
    r"(public\s+notice|cma|capital\s+markets|enforcement|license|approval|warning|guidance|sanction|notice)",
    flags=re.IGNORECASE,
)


def _is_candidate_url(href: str) -> bool:
    parsed = urlparse(href)
    path = (parsed.path or "").lower()
    return "/public-notice/" in path or path.endswith(".pdf")


def _extract_rows(source: SourceConfig, html: str) -> list[RawAnnouncement]:
    soup = BeautifulSoup(html, "lxml")
    out: list[RawAnnouncement] = []
    now_utc = datetime.now(timezone.utc)

    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        headline = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not headline:
            continue
        if len(headline) < 12:
            continue

        full_url = urljoin(source.base_url, href)
        if not _is_candidate_url(full_url):
            continue
        if not _KEYWORDS.search(headline):
            continue

        out.append(
            RawAnnouncement(
                source_id=source.source_id,
                headline=headline,
                url=full_url,
                published_at=now_utc,
                extra={"href": href, "source_page": source.base_url},
            )
        )
        if len(out) >= settings.ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE:
            break

    return out


async def collect(source: SourceConfig) -> list[RawAnnouncement]:
    html = await fetch_with_retries(source, source.base_url)
    return _extract_rows(source, html)

