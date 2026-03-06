from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Awaitable, Callable
from urllib.parse import unquote

from bs4 import BeautifulSoup

from apps.scrape_core.dedupe import normalize_canonical_url


@dataclass(slots=True, frozen=True)
class SitemapUrl:
    url: str
    lastmod: datetime | None = None
    source_sitemap: str | None = None


def _parse_lastmod(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def parse_sitemap_document(xml_text: str, *, base_url: str | None = None) -> tuple[list[SitemapUrl], list[str]]:
    if not xml_text or not xml_text.strip():
        return [], []

    soup = BeautifulSoup(xml_text, "xml")
    urls: list[SitemapUrl] = []
    nested: list[str] = []

    index_nodes = soup.find_all("sitemap")
    if index_nodes:
        for node in index_nodes:
            loc_tag = node.find("loc")
            if loc_tag is None:
                continue
            loc = normalize_canonical_url(loc_tag.get_text(" ", strip=True), base_url=base_url)
            if loc:
                nested.append(loc)

    url_nodes = soup.find_all("url")
    for node in url_nodes:
        loc_tag = node.find("loc")
        if loc_tag is None:
            continue
        url = normalize_canonical_url(loc_tag.get_text(" ", strip=True), base_url=base_url)
        if not url:
            continue
        lastmod_tag = node.find("lastmod")
        urls.append(
            SitemapUrl(
                url=url,
                lastmod=_parse_lastmod(lastmod_tag.get_text(" ", strip=True) if lastmod_tag else None),
                source_sitemap=base_url,
            )
        )

    return urls, nested


async def collect_sitemap_urls(
    *,
    root_url: str,
    fetch_xml: Callable[[str], Awaitable[str]],
    max_urls: int = 200,
    lookback_hours: int = 72,
    max_sitemaps: int = 24,
) -> list[SitemapUrl]:
    root = normalize_canonical_url(root_url)
    if not root:
        return []

    queue: deque[str] = deque([root])
    visited: set[str] = set()
    collected: dict[str, SitemapUrl] = {}
    cutoff: datetime | None = None
    if int(lookback_hours) > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(lookback_hours)))

    while queue and len(visited) < max(1, int(max_sitemaps)) and len(collected) < max(1, int(max_urls)):
        sitemap_url = queue.popleft()
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)

        try:
            body = await fetch_xml(sitemap_url)
        except Exception:
            continue

        urls, nested = parse_sitemap_document(body, base_url=sitemap_url)
        for next_url in nested:
            if next_url not in visited and next_url not in queue and len(visited) + len(queue) < max(1, int(max_sitemaps)):
                queue.append(next_url)

        for item in urls:
            if cutoff is not None and item.lastmod is not None and item.lastmod < cutoff:
                continue
            existing = collected.get(item.url)
            if existing is None:
                collected[item.url] = item
            elif existing.lastmod is None and item.lastmod is not None:
                collected[item.url] = item
            elif (
                existing.lastmod is not None
                and item.lastmod is not None
                and item.lastmod > existing.lastmod
            ):
                collected[item.url] = item

    rows = list(collected.values())
    rows.sort(key=lambda row: row.lastmod or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    return rows[: max(1, int(max_urls))]


def infer_headline_from_url(url: str) -> str:
    if not url:
        return ""
    clean = url.split("?", 1)[0].rstrip("/")
    slug = clean.rsplit("/", 1)[-1]
    slug = unquote(slug)
    slug = re.sub(r"\.(html?|php|aspx?)$", "", slug, flags=re.I)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()
    if len(slug) <= 2:
        return ""
    return slug.title()
