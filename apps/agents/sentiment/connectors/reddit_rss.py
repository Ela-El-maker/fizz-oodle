from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup

from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text

settings = get_settings()


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def collect(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    result = await fetch_text(
        url=source.base_url,
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
        return []

    soup = BeautifulSoup(result.text, "xml")
    out: list[RawPost] = []
    now = utc_now()

    for item in soup.find_all(["entry", "item"]):
        title = normalize_text(item.title.get_text(" ", strip=True) if item.title else "")
        content = ""
        if item.find("content"):
            content = normalize_text(item.find("content").get_text(" ", strip=True))
        elif item.find("description"):
            content = normalize_text(item.find("description").get_text(" ", strip=True))
        if not content:
            content = title

        link = None
        link_node = item.find("link")
        if link_node:
            link = link_node.get("href") or link_node.get_text(" ", strip=True)

        published_raw = None
        for key in ("updated", "published", "pubDate"):
            node = item.find(key)
            if node and node.get_text(strip=True):
                published_raw = node.get_text(strip=True)
                break
        published_at = _parse_date(published_raw)

        event_dt = published_at or now
        if event_dt < from_dt or event_dt > to_dt:
            continue

        out.append(
            RawPost(
                source_id=source.source_id,
                url=link,
                canonical_url=canonicalize_url(link, base_url=source.base_url),
                author=(item.find("author").get_text(" ", strip=True) if item.find("author") else None),
                title=title,
                content=content,
                published_at=published_at,
                fetched_at=now,
                raw_payload={"title": title, "link": link},
            )
        )

    return out
