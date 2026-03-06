from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from apps.agents.sentiment.connectors.reddit_rss import collect as collect_reddit_rss
from apps.agents.sentiment.extract import alias_map
from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

DEFAULT_SUBREDDITS = ("Kenya", "investing", "africa", "stocks")


def _query_aliases(limit: int = 60) -> list[str]:
    # Keep queries bounded for predictable runtime.
    candidates = sorted({k for k in alias_map().keys() if len(k) >= 3})
    return candidates[:limit]


def _comment_url(permalink: str | None) -> str | None:
    if not permalink:
        return None
    if permalink.startswith("http://") or permalink.startswith("https://"):
        return permalink
    return f"https://www.reddit.com{permalink}"


def _safe_author(obj: object) -> str | None:
    try:
        author = getattr(obj, "author", None)
        return str(author) if author else None
    except Exception:
        return None


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


async def _collect_with_asyncpraw(
    source: SentimentSourceConfig,
    from_dt: datetime,
    to_dt: datetime,
) -> list[RawPost]:
    try:
        import asyncpraw  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"missing_dependency: {exc}") from exc

    client_id = (settings.REDDIT_CLIENT_ID or "").strip()
    client_secret = (settings.REDDIT_CLIENT_SECRET or "").strip()
    user_agent = (settings.REDDIT_USER_AGENT or settings.USER_AGENT or "").strip()
    if not client_id or not client_secret or not user_agent:
        raise RuntimeError("missing_key: REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET/REDDIT_USER_AGENT")

    now = utc_now()
    terms = _query_aliases()
    seen: set[str] = set()
    out: list[RawPost] = []
    max_items = max(1, int(source.max_items_per_run))

    reddit = asyncpraw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    try:
        for sub_name in DEFAULT_SUBREDDITS:
            subreddit = await reddit.subreddit(sub_name)
            for term in terms:
                async for submission in subreddit.search(term, time_filter="week", sort="new", limit=100):
                    created = datetime.fromtimestamp(float(getattr(submission, "created_utc", 0.0)), tz=timezone.utc)
                    if created < from_dt or created > to_dt:
                        continue

                    permalink = _comment_url(getattr(submission, "permalink", None))
                    title = normalize_text(getattr(submission, "title", ""))
                    selftext = normalize_text(getattr(submission, "selftext", ""))[:500]
                    content = normalize_text(f"{title}. {selftext}".strip(". "))
                    if not content:
                        continue
                    key = f"post|{permalink}|{content[:200]}"
                    if key in seen:
                        continue
                    seen.add(key)
                    engagement = _safe_int(getattr(submission, "score", 0))
                    out.append(
                        RawPost(
                            source_id=source.source_id,
                            url=permalink,
                            canonical_url=canonicalize_url(permalink),
                            author=_safe_author(submission),
                            title=title or None,
                            content=content,
                            published_at=created,
                            fetched_at=now,
                            raw_payload={
                                "platform": "reddit",
                                "kind": "post",
                                "engagement": engagement,
                                "subreddit": sub_name,
                            },
                        )
                    )
                    if len(out) >= max_items:
                        return out

                    # Top comments.
                    try:
                        await submission.comments.replace_more(limit=0)
                        comments = submission.comments.list()[:50]
                    except Exception:
                        comments = []
                    for comment in comments:
                        try:
                            c_body = normalize_text(getattr(comment, "body", ""))
                            if not c_body:
                                continue
                            c_created = datetime.fromtimestamp(
                                float(getattr(comment, "created_utc", 0.0)),
                                tz=timezone.utc,
                            )
                            if c_created < from_dt or c_created > to_dt:
                                continue
                            c_url = _comment_url(getattr(comment, "permalink", None)) or permalink
                            c_key = f"comment|{c_url}|{c_body[:200]}"
                            if c_key in seen:
                                continue
                            seen.add(c_key)
                            c_engagement = _safe_int(getattr(comment, "score", 0))
                            out.append(
                                RawPost(
                                    source_id=source.source_id,
                                    url=c_url,
                                    canonical_url=canonicalize_url(c_url),
                                    author=_safe_author(comment),
                                    title=title or None,
                                    content=c_body,
                                    published_at=c_created,
                                    fetched_at=now,
                                    raw_payload={
                                        "platform": "reddit",
                                        "kind": "comment",
                                        "engagement": c_engagement,
                                        "subreddit": sub_name,
                                    },
                                )
                            )
                            if len(out) >= max_items:
                                return out
                        except Exception:
                            continue
    finally:
        try:
            await reddit.close()
        except Exception:
            pass

    return out


def _fallback_source(source: SentimentSourceConfig) -> SentimentSourceConfig:
    if ".rss" in (source.base_url or ""):
        return source
    return SentimentSourceConfig(
        source_id=source.source_id,
        type=source.type,
        base_url="https://www.reddit.com/r/Kenya+NSE+AfricaBusiness+stocks/new/.rss",
        enabled_by_default=source.enabled_by_default,
        parser="reddit_rss.collect",
        timeout_secs=source.timeout_secs,
        retries=source.retries,
        backoff_base=source.backoff_base,
        rate_limit_rps=source.rate_limit_rps,
        weight=source.weight,
        requires_auth=False,
        tier=source.tier,
        required_for_success=source.required_for_success,
        cache_ttl_seconds=source.cache_ttl_seconds,
        use_conditional_get=source.use_conditional_get,
        max_items_per_run=source.max_items_per_run,
        auth_env_key=None,
    )


async def collect(source: SentimentSourceConfig, from_dt: datetime, to_dt: datetime) -> list[RawPost]:
    try:
        return await _collect_with_asyncpraw(source, from_dt, to_dt)
    except Exception as exc:
        # Fallback to RSS keeps the source operational when OAuth/dependency is missing.
        logger.info("reddit_praw_fallback_to_rss", source_id=source.source_id, reason=str(exc))
        return await collect_reddit_rss(_fallback_source(source), from_dt, to_dt)
