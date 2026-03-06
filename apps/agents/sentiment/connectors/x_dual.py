from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text

settings = get_settings()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _safe_int(v: object, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


async def _collect_api(source: SentimentSourceConfig, token: str, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    headers = {
        "User-Agent": settings.USER_AGENT,
        "Authorization": f"Bearer {token}",
    }
    params = {
        "query": "NSE OR Safaricom OR KCB OR Equity OR NCBA OR EABL lang:en -is:retweet",
        "max_results": 100,
        "start_time": from_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tweet.fields": "created_at,public_metrics,lang",
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
    out: list[RawPost] = []
    for item in payload.get("data", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        text = normalize_text(item.get("text"))
        if not text:
            continue
        tweet_id = str(item.get("id", "")).strip()
        if not tweet_id:
            continue
        url = f"https://x.com/i/web/status/{tweet_id}"
        published_at = _parse_iso(item.get("created_at"))
        event_dt = published_at or now
        if event_dt < from_dt or event_dt > to_dt:
            continue

        metrics = item.get("public_metrics") if isinstance(item.get("public_metrics"), dict) else {}
        engagement = (
            _safe_int(metrics.get("like_count"))
            + _safe_int(metrics.get("retweet_count"))
            + _safe_int(metrics.get("reply_count"))
            + _safe_int(metrics.get("quote_count"))
        )
        out.append(
            RawPost(
                source_id=source.source_id,
                url=url,
                canonical_url=canonicalize_url(url),
                author=None,
                title=None,
                content=text,
                published_at=published_at,
                fetched_at=now,
                raw_payload={"platform": "x", "engagement": engagement, "tweet": item},
            )
        )
    return out


async def _collect_nitter(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    base = (settings.X_NITTER_BASE_URL or "https://nitter.net").rstrip("/")
    result = await fetch_text(
        url=f"{base}/search",
        timeout_secs=source.timeout_secs,
        retries=source.retries,
        backoff_base=source.backoff_base,
        rate_limit_rps=source.rate_limit_rps,
        headers={"User-Agent": settings.USER_AGENT},
        params={"q": "NSE OR Safaricom OR KCB OR Equity", "f": "tweets"},
    )
    if not result.ok:
        raise RuntimeError(f"{result.error_type or 'fetch_error'}: {result.error or 'failed'}")

    soup = BeautifulSoup(result.text, "html.parser")
    now = utc_now()
    out: list[RawPost] = []
    seen: set[str] = set()

    for item in soup.select(".timeline-item, article"):
        text_node = item.select_one(".tweet-content, .tweet-body, p")
        text = normalize_text(text_node.get_text(" ", strip=True) if text_node else "")
        if not text:
            continue
        link_node = item.select_one("a[href*='/status/']")
        href = link_node.get("href") if link_node else None
        if not href:
            continue
        url = urljoin(base + "/", href)
        key = f"{url}|{text[:120]}"
        if key in seen:
            continue
        seen.add(key)

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
                raw_payload={"platform": "nitter", "engagement": 0},
            )
        )
        if len(out) >= source.max_items_per_run:
            break

    # Keep posts inside requested time window when published timestamps are available.
    # For scraped nitter rows we usually have no reliable published_at; keep them so
    # they can still contribute to weekly sentiment windows.
    filtered: list[RawPost] = []
    for row in out:
        if row.published_at is None or (from_dt <= row.published_at <= to_dt):
            filtered.append(row)
    return filtered


async def collect(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    env_key = source.auth_env_key or "X_API_BEARER_TOKEN"
    token = (getattr(settings, env_key, "") or "").strip()

    if token:
        try:
            rows = await _collect_api(source, token=token, from_dt=from_dt, to_dt=to_dt)
            if rows:
                return rows[: source.max_items_per_run]
        except Exception:
            # Fall back to nitter parser on API failure.
            pass

    rows = await _collect_nitter(source, from_dt=from_dt, to_dt=to_dt)
    return rows[: source.max_items_per_run]
