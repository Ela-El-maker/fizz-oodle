from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from apps.agents.sentiment.extract import extract_tickers
from apps.agents.sentiment.normalize import canonicalize_url, normalize_text, utc_now
from apps.agents.sentiment.types import RawPost, SentimentSourceConfig
from apps.core.config import get_settings
from apps.scrape_core.http_client import fetch_text

settings = get_settings()

_GLOBAL_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oil": ("oil", "brent", "crude", "opec", "fuel", "shipping"),
    "commodities": ("commodity", "commodities", "metals", "agriculture"),
    "usd_strength": ("usd", "dollar", "fed", "rates", "forex", "fx"),
    "bonds_yields": ("bond", "bonds", "yield", "yields", "treasury", "sovereign debt"),
    "earnings_cycle": ("earnings", "guidance", "profit warning", "eps"),
    "dividends_flow": ("dividend", "payout", "book closure", "yield"),
    "global_equities_trading": ("stocks", "equities", "index", "trading", "risk off", "risk-on", "selloff"),
    "global_risk": ("volatility", "risk off", "risk-on", "drawdown"),
    "ai_platforms": ("openai", "deepmind", "anthropic", "ai", "llm", "model", "gpu"),
    "ai_research": ("ai research", "benchmark", "training", "inference"),
    "global_tech_risk": ("ai", "chip", "gpu", "cloud", "platform"),
}


def _has_global_theme_signal(text: str, source: SentimentSourceConfig) -> bool:
    low = text.lower()
    source_theme = (source.theme or "").strip().lower()
    if source_theme:
        terms = _GLOBAL_THEME_KEYWORDS.get(source_theme, (source_theme,))
        if any(term in low for term in terms):
            return True
    for terms in _GLOBAL_THEME_KEYWORDS.values():
        if any(term in low for term in terms):
            return True
    return False


def _iter_candidates(soup: BeautifulSoup) -> list[tuple[str, str | None]]:
    candidates: list[tuple[str, str | None]] = []
    primary_nodes = soup.select("article, .comment, .post, .forum-post, .entry")
    nodes = primary_nodes or soup.select("li, p")
    for node in nodes:
        text = normalize_text(node.get_text(" ", strip=True))
        if len(text) < 40:
            continue
        href = None
        link = node.find("a", href=True)
        if link:
            href = str(link.get("href") or "").strip() or None
        candidates.append((text, href))
    if not candidates:
        for link in soup.select("a[href]"):
            text = normalize_text(link.get_text(" ", strip=True))
            if len(text) < 40:
                continue
            candidates.append((text, str(link.get("href") or "").strip() or None))
    return candidates


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

    soup = BeautifulSoup(result.text, "html.parser")
    now = utc_now()
    seen: set[str] = set()
    out: list[RawPost] = []

    for text, href in _iter_candidates(soup):
        tickers = extract_tickers(text)
        global_theme_match = source.scope == "global_outside" and _has_global_theme_signal(text, source)
        if not tickers and not global_theme_match:
            continue
        resolved_url = urljoin(source.base_url, href) if href else source.base_url
        key = f"{(resolved_url or '').lower()}|{text[:220].lower()}"
        if key in seen:
            continue
        seen.add(key)

        out.append(
            RawPost(
                source_id=source.source_id,
                url=resolved_url,
                canonical_url=canonicalize_url(resolved_url, base_url=source.base_url),
                author=None,
                title=text[:120],
                content=text,
                published_at=None,
                fetched_at=now,
                raw_payload={
                    "platform": "html_discussion",
                    "engagement": 0,
                    "signal_mode": "theme" if global_theme_match and not tickers else "ticker",
                },
            )
        )
        if len(out) >= source.max_items_per_run:
            break

    filtered: list[RawPost] = []
    for row in out:
        if row.published_at is None or (from_dt <= row.published_at <= to_dt):
            filtered.append(row)
    return filtered
