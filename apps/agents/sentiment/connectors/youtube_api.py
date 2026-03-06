from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from urllib.parse import urljoin

from apps.agents.sentiment.extract import ticker_company_map
from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text

settings = get_settings()


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


async def collect(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    env_key = source.auth_env_key or "YOUTUBE_API_KEY"
    api_key = (getattr(settings, env_key, "") or "").strip()
    if source.requires_auth and not api_key:
        return []

    headers = {"User-Agent": settings.USER_AGENT}
    now = utc_now()
    out: list[RawPost] = []
    seen: set[str] = set()
    max_items = max(1, int(source.max_items_per_run))
    max_companies = 10
    max_videos_per_company = 5
    max_comments_per_video = 50

    company_terms = list(ticker_company_map().values())[:max_companies]
    if not company_terms:
        company_terms = ["NSE Kenya stocks"]

    async def _search_videos(term: str) -> list[str]:
        result = await fetch_text(
            url=source.base_url,
            timeout_secs=source.timeout_secs,
            retries=source.retries,
            backoff_base=source.backoff_base,
            rate_limit_rps=source.rate_limit_rps,
            headers=headers,
            params={
                "part": "snippet",
                "type": "video",
                "order": "date",
                "maxResults": 10,
                "q": f"{term} stock Kenya NSE",
                "publishedAfter": from_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "key": api_key,
            },
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
        ids: list[str] = []
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            vid = ((item.get("id") or {}).get("videoId") if isinstance(item.get("id"), dict) else None) or None
            if vid:
                ids.append(str(vid))
            if len(ids) >= max_videos_per_company:
                break
        return ids

    base = source.base_url.rsplit("/", 1)[0]
    comments_url = urljoin(base + "/", "commentThreads")
    sem = asyncio.Semaphore(5)

    async def _collect_video_comments(video_id: str) -> list[RawPost]:
        async with sem:
            result = await fetch_text(
                url=comments_url,
                timeout_secs=source.timeout_secs,
                retries=source.retries,
                backoff_base=source.backoff_base,
                rate_limit_rps=source.rate_limit_rps,
                headers=headers,
                params={
                    "part": "snippet",
                    "videoId": video_id,
                    "maxResults": max_comments_per_video,
                    "order": "relevance",
                    "textFormat": "plainText",
                    "key": api_key,
                },
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

        rows: list[RawPost] = []
        for item in payload.get("items", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            tlc = snippet.get("topLevelComment") if isinstance(snippet.get("topLevelComment"), dict) else {}
            c_snippet = tlc.get("snippet") if isinstance(tlc.get("snippet"), dict) else {}
            text = normalize_text(c_snippet.get("textDisplay") or c_snippet.get("textOriginal"))
            if not text:
                continue
            published_at = _parse_published_at(c_snippet.get("publishedAt"))
            event_dt = published_at or now
            if event_dt < from_dt or event_dt > to_dt:
                continue
            comment_id = str(item.get("id") or "").strip() or None
            url = f"https://www.youtube.com/watch?v={video_id}" + (f"&lc={comment_id}" if comment_id else "")
            key = f"{url}|{text[:180]}"
            if key in seen:
                continue
            seen.add(key)
            engagement = int(c_snippet.get("likeCount") or 0)
            rows.append(
                RawPost(
                    source_id=source.source_id,
                    url=url,
                    canonical_url=canonicalize_url(url),
                    author=c_snippet.get("authorDisplayName"),
                    title=None,
                    content=text,
                    published_at=published_at,
                    fetched_at=now,
                    raw_payload={
                        "platform": "youtube",
                        "video_id": video_id,
                        "comment_id": comment_id,
                        "engagement": engagement,
                    },
                )
            )
            if len(rows) >= max_items:
                break
        return rows

    video_ids: list[str] = []
    for term in company_terms:
        ids = await _search_videos(term)
        video_ids.extend(ids)

    if not video_ids:
        return []

    tasks = [_collect_video_comments(vid) for vid in dict.fromkeys(video_ids)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            continue
        out.extend(result)
        if len(out) >= max_items:
            break
    return out[:max_items]
