from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from apps.scrape_core.http_client import fetch_text
from apps.agents.announcements.types import RawAnnouncement, SourceConfig
from apps.core.config import get_settings

settings = get_settings()
_RUN_HTTP_CLIENT: ContextVar[httpx.AsyncClient | None] = ContextVar("agent_b_run_http_client", default=None)

_KENYA_DISCLOSURE_PATTERN = re.compile(
    r"(dividend|results|agm|egm|notice|board|suspension|earnings|profit|rights|acquisition)",
    re.I,
)
_KENYA_EXTENDED_PATTERN = re.compile(
    r"(market|economy|bank|banking|nse|cbk|cma|earnings|dividend|shares|stocks|ipo|bond|yield|currency|shilling)",
    re.I,
)
_GLOBAL_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oil": ("oil", "brent", "crude", "opec", "fuel", "shipping", "freight"),
    "commodities": ("commodity", "commodities", "metals", "agriculture", "energy"),
    "usd_strength": ("usd", "u.s. dollar", "dollar index", "fed", "federal reserve", "fx", "forex"),
    "bonds_yields": ("bond", "bonds", "yield", "yields", "treasury", "sovereign debt", "coupon"),
    "earnings_cycle": ("earnings", "guidance", "profit warning", "quarterly results", "eps"),
    "dividends_flow": ("dividend", "payout", "yield", "book closure", "shareholder return"),
    "global_equities_trading": ("stocks", "equities", "trading", "risk off", "risk-on", "index", "volatility"),
    "global_risk": ("volatility", "drawdown", "risk off", "risk-on", "selloff", "flight to safety"),
    "global_macro": ("inflation", "rates", "gdp", "recession", "macro", "central bank", "liquidity"),
    "ai_platforms": ("ai", "openai", "deepmind", "anthropic", "llm", "model release", "gpu", "inference"),
    "ai_research": ("ai research", "benchmark", "model", "training", "inference", "compute"),
    "global_tech_risk": ("ai", "chip", "gpu", "cloud", "platform risk", "cybersecurity"),
    "kenya_business_news": ("kenya", "nairobi", "nse", "cbk", "cma", "business"),
}
_GLOBAL_GENERIC_PATTERN = re.compile(
    r"(market|stocks|equities|trading|bonds?|yields?|oil|brent|dollar|fed|rates?|inflation|earnings?|dividend|ai|technology)",
    re.I,
)


class SourceFetchError(Exception):
    def __init__(self, message: str, *, error_type: str, status_code: int | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.status_code = status_code


def classify_source_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, SourceFetchError):
        return exc.error_type, str(exc)
    if isinstance(exc, (httpx.ReadTimeout, httpx.TimeoutException)):
        return "timeout", str(exc)
    if isinstance(exc, httpx.ConnectError):
        msg = str(exc).lower()
        if "name or service not known" in msg or "nodename nor servname provided" in msg:
            return "dns_error", str(exc)
        return "connection_error", str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in {401, 403}:
            return "blocked", str(exc)
        if code == 429:
            return "rate_limited", str(exc)
        if code >= 500:
            return "upstream_5xx", str(exc)
        return "http_error", str(exc)
    return "unknown_error", str(exc)


@contextmanager
def bind_http_client(client: httpx.AsyncClient):
    token = _RUN_HTTP_CLIENT.set(client)
    try:
        yield
    finally:
        _RUN_HTTP_CLIENT.reset(token)


async def fetch_with_retries(source: SourceConfig, url: str) -> str:
    headers = {"User-Agent": settings.USER_AGENT}
    if source.requires_auth and source.auth_env_key:
        token = getattr(settings, source.auth_env_key, "")
        if not token:
            raise SourceFetchError("missing source auth key", error_type="missing_key")
        headers["Authorization"] = f"Bearer {token}"

    shared_client = _RUN_HTTP_CLIENT.get()
    result = await fetch_text(
        url=url,
        timeout_secs=source.timeout_secs,
        retries=source.retries,
        backoff_base=source.backoff_base,
        rate_limit_rps=source.rate_limit_rps,
        headers=headers,
        use_conditional_get=source.use_conditional_get,
        cache_ttl_seconds=source.cache_ttl_seconds,
        client=shared_client,
    )
    if result.ok and not result.not_modified:
        return result.text
    if result.ok and result.not_modified:
        return ""
    raise SourceFetchError(
        result.error or "fetch failed",
        error_type=result.error_type or "unknown_error",
        status_code=result.status_code,
    )


def parse_html_anchors(source: SourceConfig, html: str) -> list[RawAnnouncement]:
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[RawAnnouncement] = []

    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        headline = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not headline:
            continue
        if len(headline) < 15:
            continue
        if not _headline_relevant_for_source(source, headline):
            continue

        out.append(
            RawAnnouncement(
                source_id=source.source_id,
                headline=headline,
                url=urljoin(source.base_url, href),
                published_at=datetime.now(timezone.utc),
                extra={"href": href},
            )
        )
        if len(out) >= min(settings.ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE, source.max_items_per_run):
            break

    return out


def _headline_relevant_for_source(source: SourceConfig, headline: str) -> bool:
    text = (headline or "").strip().lower()
    if not text:
        return False

    if source.scope == "kenya_core":
        return _KENYA_DISCLOSURE_PATTERN.search(text) is not None

    if source.scope == "kenya_extended":
        return _KENYA_EXTENDED_PATTERN.search(text) is not None

    # Global-outside lane accepts broader market signals gated by theme keywords.
    theme = (source.theme or "").strip().lower()
    theme_terms = _GLOBAL_THEME_KEYWORDS.get(theme, ())
    if theme_terms and any(term in text for term in theme_terms):
        return True
    if _GLOBAL_GENERIC_PATTERN.search(text):
        return True
    return False


def parse_rss_items(source: SourceConfig, xml_text: str) -> list[RawAnnouncement]:
    if not xml_text:
        return []
    soup = BeautifulSoup(xml_text, "xml")
    out: list[RawAnnouncement] = []

    for item in soup.find_all(["item", "entry"]):
        title_tag = item.find("title")
        link_tag = item.find("link")

        headline = " ".join((title_tag.get_text(" ", strip=True) if title_tag else "").split())
        if link_tag is None:
            continue
        link = (link_tag.get("href") or link_tag.get_text(" ", strip=True) or "").strip()
        if not headline or not link or not link.startswith(("http://", "https://", "/")):
            continue

        pub = item.find("pubDate") or item.find("published") or item.find("updated")
        published_at = pub.get_text(" ", strip=True) if pub else datetime.now(timezone.utc)

        out.append(
            RawAnnouncement(
                source_id=source.source_id,
                headline=headline,
                url=urljoin(source.base_url, link),
                published_at=published_at,
                extra={},
            )
        )
        if len(out) >= min(settings.ANNOUNCEMENTS_MAX_ITEMS_PER_SOURCE, source.max_items_per_run):
            break

    return out
