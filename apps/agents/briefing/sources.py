from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

from apps.agents.briefing.normalize import parse_float, utc_now
from apps.agents.briefing.types import FxPoint, HeadlinePoint, IndexPoint, PricePoint
from apps.core.config import get_settings
from apps.scrape_core.dedupe import content_fingerprint, normalize_canonical_url
from apps.scrape_core.http_client import fetch_text
from apps.scrape_core.sitemap import collect_sitemap_urls, infer_headline_from_url

settings = get_settings()

MYSTOCKS_BASE = "https://live.mystocks.co.ke"
NSE_MARKET_STATS_URL = "https://www.nse.co.ke/market-statistics/"
NSE_HOME_URL = "https://www.nse.co.ke/"
STANDARD_BUSINESS_RSS_URL = "https://www.standardmedia.co.ke/rss/business.php"
BUSINESS_DAILY_HTML_URL = "https://www.businessdailyafrica.com/bd/markets"
THE_STAR_BUSINESS_HTML_URL = "https://www.the-star.co.ke/business/"
STANDARD_BUSINESS_HTML_URL = "https://www.standardmedia.co.ke/business"
BBC_BUSINESS_RSS_URL = "https://feeds.bbci.co.uk/news/business/rss.xml"
GOOGLE_NEWS_KE_RSS_URL = (
    "https://news.google.com/rss/search?"
    "q=NSE+Kenya+stocks+OR+%22Nairobi+Securities+Exchange%22+when:7d&hl=en-KE&gl=KE&ceid=KE:en"
)


async def _http_get(
    url: str,
    timeout: int = 30,
    *,
    retries: int = 2,
    backoff_base: float = 2.0,
    rate_limit_rps: float = 0.3,
    use_conditional_get: bool = False,
    cache_ttl_seconds: int = 0,
) -> str:
    result = await fetch_text(
        url=url,
        timeout_secs=timeout,
        retries=retries,
        backoff_base=backoff_base,
        rate_limit_rps=rate_limit_rps,
        headers={"User-Agent": settings.USER_AGENT},
        use_conditional_get=use_conditional_get,
        cache_ttl_seconds=cache_ttl_seconds,
    )
    if result.ok:
        return result.text
    raise RuntimeError(f"{result.error_type or 'fetch_error'}: {result.error or 'failed'}")


def _extract_price_from_title(title_text: str) -> float | None:
    m = re.search(r"Price:\s*KES\s*([0-9]+(?:\.[0-9]+)?)", title_text, flags=re.I)
    return parse_float(m.group(1)) if m else None


def _extract_th_td(soup: BeautifulSoup) -> dict[str, str]:
    kv: dict[str, str] = {}
    for th in soup.select("th"):
        key = th.get_text(" ", strip=True)
        td = th.find_next_sibling("td")
        if not key or td is None:
            continue
        kv[key.lower().strip()] = td.get_text(" ", strip=True)
    return kv


def _parse_rss_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _index_point_from_text(target_date, now, index_name: str, text: str, source_id: str) -> IndexPoint | None:
    escaped = re.escape(index_name)
    pattern_signed = re.compile(
        rf"{escaped}\s*[:\-]?\s*([0-9,]+(?:\.[0-9]+)?)\s*([+-][0-9,]+(?:\.[0-9]+)?)\s*%?",
        flags=re.I,
    )
    pattern_value_only = re.compile(
        rf"{escaped}\s*[:\-]?\s*([0-9,]+(?:\.[0-9]+)?)",
        flags=re.I,
    )

    match = pattern_signed.search(text)
    if match:
        value = parse_float(match.group(1))
        change_val = parse_float(match.group(2))
        return IndexPoint(
            date=target_date,
            index_name="NASI" if index_name.upper().startswith("NSE ALL SHARE") else index_name.replace(" ", ""),
            value=value,
            change_val=change_val,
            pct_change=change_val,
            source_id=source_id,
            fetched_at=now,
            raw_payload={"match": match.group(0), "source_label": index_name},
        )

    match = pattern_value_only.search(text)
    if not match:
        return None
    value = parse_float(match.group(1))
    return IndexPoint(
        date=target_date,
        index_name="NASI" if index_name.upper().startswith("NSE ALL SHARE") else index_name.replace(" ", ""),
        value=value,
        change_val=None,
        pct_change=None,
        source_id=source_id,
        fetched_at=now,
        raw_payload={"match": match.group(0), "source_label": index_name},
    )


def _is_valid_index_point(row: IndexPoint) -> bool:
    if row.value is None:
        return False
    if row.value < float(settings.AGENT_A_INDEX_MIN_VALUE):
        return False
    if row.value > float(settings.AGENT_A_INDEX_MAX_VALUE):
        return False
    if row.pct_change is not None and abs(float(row.pct_change)) > float(settings.AGENT_A_INDEX_MAX_PCT_MOVE):
        return False
    return True


async def fetch_index_nasi_resilient(target_date) -> tuple[list[IndexPoint], dict[str, str | None]]:
    diagnostics: dict[str, str | None] = {"source_used": None, "error": None, "status": "missing"}
    candidates: list[tuple[str, Any]] = [
        ("nse_market_stats", fetch_index_nse_market_stats),
        ("nse_home", None),
        ("mystocks", fetch_index_mystocks),
    ]

    for source_id, fetcher in candidates:
        try:
            if source_id == "nse_home":
                html = await _http_get(
                    NSE_HOME_URL,
                    timeout=30,
                    retries=2,
                    backoff_base=2.0,
                    rate_limit_rps=0.25,
                    use_conditional_get=True,
                    cache_ttl_seconds=300,
                )
                text = " ".join(BeautifulSoup(html, "lxml").stripped_strings)
                now = utc_now()
                rows = []
                for label in ("NSE ALL SHARE INDEX", "NASI", "NSE 20 SHARE INDEX", "NSE 25 SHARE INDEX"):
                    row = _index_point_from_text(target_date, now, label, text, "nse_home")
                    if row:
                        rows.append(row)
            else:
                rows = await fetcher(target_date)

            if not rows:
                diagnostics["error"] = f"{source_id}: empty"
                continue

            normalized: list[IndexPoint] = []
            for row in rows:
                if row.index_name not in {"NASI", "NSE20", "NSE25"}:
                    continue
                if not _is_valid_index_point(row):
                    continue
                if any(existing.index_name == row.index_name for existing in normalized):
                    continue
                normalized.append(row)

            if not normalized:
                diagnostics["error"] = f"{source_id}: sanity_reject"
                continue

            diagnostics["source_used"] = source_id
            diagnostics["status"] = "fresh"
            diagnostics["error"] = None
            return normalized, diagnostics
        except Exception as exc:  # noqa: PERF203
            diagnostics["error"] = f"{source_id}: {exc}"
            continue

    diagnostics["status"] = "missing"
    return [], diagnostics


async def _fetch_headlines_rss(
    target_date,
    source_id: str,
    rss_url: str,
    *,
    max_items: int | None = None,
) -> list[HeadlinePoint]:
    xml_text = await _http_get(rss_url)
    soup = BeautifulSoup(xml_text, "xml")
    now = utc_now()

    item_cap = max_items if isinstance(max_items, int) and max_items > 0 else 20

    out: list[HeadlinePoint] = []
    seen: set[str] = set()
    for item in soup.find_all(["item", "entry"]):
        title_tag = item.find("title")
        title = " ".join((title_tag.get_text(" ", strip=True) if title_tag else "").split())
        if not title:
            continue

        link_tag = item.find("link")
        if link_tag is None:
            continue
        link = (link_tag.get("href") or link_tag.get_text(" ", strip=True) or "").strip()
        if not link:
            continue
        url = str(httpx.URL(rss_url).join(link))
        if url in seen:
            continue
        seen.add(url)

        pub_tag = item.find("pubDate") or item.find("published") or item.find("updated")
        published_at = _parse_rss_datetime(pub_tag.get_text(" ", strip=True) if pub_tag else None)

        out.append(
            HeadlinePoint(
                date=target_date,
                source_id=source_id,
                headline=title,
                url=url,
                published_at=published_at,
                fetched_at=now,
            )
        )
        if len(out) >= item_cap:
            break
    return out


def _match_aliases(headline: str, alias_map: dict[str, set[str]]) -> list[str]:
    text = (headline or "").lower()
    matched: list[str] = []
    for ticker, aliases in alias_map.items():
        if any(alias in text for alias in aliases):
            matched.append(ticker)
    return matched


def _extract_headlines_html(
    *,
    html: str,
    base_url: str,
    source_id: str,
    target_date,
    alias_map: dict[str, set[str]] | None,
    trust_rank: int = 3,
    relevance_base: float = 0.5,
    require_alias_matches: bool = True,
    max_items: int | None = None,
) -> list[HeadlinePoint]:
    soup = BeautifulSoup(html, "lxml")
    now = utc_now()
    out: list[HeadlinePoint] = []
    seen: set[str] = set()
    alias_map = alias_map or {}

    selectors = [
        "article a[href]",
        ".article-list a[href]",
        ".story a[href]",
        ".title a[href]",
        "a[href]",
    ]
    links: list[Any] = []
    for selector in selectors:
        links = soup.select(selector)
        if links:
            break

    for anchor in links:
        title = " ".join(anchor.get_text(" ", strip=True).split())
        href = (anchor.get("href") or "").strip()
        if not title or not href:
            continue
        if len(title) < 30:
            continue
        url = normalize_canonical_url(href, base_url=base_url)
        if not url or url in seen:
            continue
        seen.add(url)
        matched_tickers = _match_aliases(title, alias_map) if alias_map else []
        if require_alias_matches and alias_map and not matched_tickers:
            continue
        hash_value = content_fingerprint(title.lower().strip(), url)
        relevance = min(1.0, relevance_base + (0.1 * len(matched_tickers)))
        confidence = min(1.0, 0.35 + (0.1 * trust_rank) + (0.05 * len(matched_tickers)))
        out.append(
            HeadlinePoint(
                date=target_date,
                source_id=source_id,
                headline=title,
                url=url,
                published_at=None,
                fetched_at=now,
                matched_tickers=matched_tickers,
                content_hash=hash_value,
                trust_rank=trust_rank,
                relevance_score=relevance,
                confidence=confidence,
                raw_payload=None,
            )
        )
        if len(out) >= item_cap:
            break
    return out


async def fetch_headlines_rss_generic(
    target_date,
    *,
    source_id: str,
    rss_url: str,
    max_items: int,
) -> list[HeadlinePoint]:
    return await _fetch_headlines_rss(target_date, source_id, rss_url, max_items=max_items)


async def fetch_headlines_html_listing_generic(
    target_date,
    *,
    source_id: str,
    base_url: str,
    alias_map: dict[str, set[str]],
    trust_rank: int = 3,
    relevance_base: float = 0.55,
    max_items: int = 25,
    require_alias_matches: bool = True,
) -> list[HeadlinePoint]:
    html = await _http_get(
        base_url,
        timeout=30,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.25,
    )
    return _extract_headlines_html(
        html=html,
        base_url=base_url,
        source_id=source_id,
        target_date=target_date,
        alias_map=alias_map,
        trust_rank=trust_rank,
        relevance_base=relevance_base,
        require_alias_matches=require_alias_matches,
        max_items=max_items,
    )


async def fetch_headlines_sitemap(
    target_date,
    *,
    source_id: str,
    sitemap_url: str,
    trust_rank: int = 3,
    relevance_base: float = 0.5,
    max_items: int = 50,
) -> list[HeadlinePoint]:
    async def _fetch_sitemap(url: str) -> str:
        return await _http_get(
            url,
            timeout=30,
            retries=2,
            backoff_base=2.0,
            rate_limit_rps=0.2,
            use_conditional_get=True,
            cache_ttl_seconds=300,
        )

    entries = await collect_sitemap_urls(
        root_url=sitemap_url,
        fetch_xml=_fetch_sitemap,
        max_urls=max(1, int(max_items)),
        lookback_hours=max(1, int(settings.SITEMAP_LOOKBACK_HOURS)),
    )
    now = utc_now()
    out: list[HeadlinePoint] = []
    seen: set[str] = set()

    for item in entries:
        if item.url in seen:
            continue
        seen.add(item.url)
        headline = infer_headline_from_url(item.url)
        if len(headline) < 12:
            continue
        out.append(
            HeadlinePoint(
                date=target_date,
                source_id=source_id,
                headline=headline,
                url=item.url,
                published_at=item.lastmod,
                fetched_at=now,
                matched_tickers=None,
                content_hash=content_fingerprint(headline.lower().strip(), item.url),
                trust_rank=trust_rank,
                relevance_score=min(1.0, max(0.1, relevance_base)),
                confidence=min(1.0, 0.35 + (0.1 * trust_rank)),
                raw_payload={
                    "sitemap_source": item.source_sitemap,
                    "lastmod": item.lastmod.isoformat() if item.lastmod else None,
                },
            )
        )
        if len(out) >= max(1, int(max_items)):
            break
    return out


async def fetch_prices_mystocks(target_date, tickers: list[str]) -> list[PricePoint]:
    out: list[PricePoint] = []
    now = utc_now()

    for ticker in tickers:
        url = f"{MYSTOCKS_BASE}/m/stock={ticker}"
        try:
            html = await _http_get(url)
        except Exception:
            continue

        soup = BeautifulSoup(html, "lxml")
        kv = _extract_th_td(soup)

        title_tag = soup.find("title")
        title_text = title_tag.get_text(" ", strip=True) if title_tag else ""

        close_price = parse_float(kv.get("average:"))
        if close_price is None:
            close_price = _extract_price_from_title(title_text)

        prev_close = parse_float(kv.get("previous:"))
        open_price = parse_float(kv.get("open:"))
        day_range = kv.get("day:") or ""
        high = low = None
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*-\s*([0-9]+(?:\.[0-9]+)?)", day_range)
        if m:
            low = parse_float(m.group(1))
            high = parse_float(m.group(2))

        volume = parse_float(kv.get("volume:"))

        if close_price is None and prev_close is None and volume is None:
            continue

        out.append(
            PricePoint(
                date=target_date,
                ticker=ticker,
                close=close_price,
                open=open_price,
                high=high,
                low=low,
                volume=volume,
                currency="KES",
                source_id="mystocks",
                fetched_at=now,
                raw_payload={"url": url, "table": kv},
            )
        )

    return out


async def fetch_index_mystocks(target_date) -> list[IndexPoint]:
    html = await _http_get(f"{MYSTOCKS_BASE}/")
    text = " ".join(BeautifulSoup(html, "lxml").stripped_strings)
    now = utc_now()

    out: list[IndexPoint] = []
    for symbol, index_name in [("NASI", "NASI"), ("N20I", "NSE20"), ("N25I", "NSE25")]:
        m = re.search(rf"\^{symbol}\s+([0-9,]+(?:\.[0-9]+)?)\s+([0-9,]+(?:\.[0-9]+)?)\s+([+-]?[0-9]+(?:\.[0-9]+)?)%", text)
        if not m:
            continue
        value = parse_float(m.group(1))
        change_val = parse_float(m.group(2))
        pct = parse_float(m.group(3))
        out.append(
            IndexPoint(
                date=target_date,
                index_name=index_name,
                value=value,
                change_val=change_val,
                pct_change=pct,
                source_id="mystocks",
                fetched_at=now,
                raw_payload={"match": m.group(0)},
            )
        )

    return out


async def fetch_index_nse_market_stats(target_date) -> list[IndexPoint]:
    html = await _http_get(NSE_MARKET_STATS_URL)
    text = " ".join(BeautifulSoup(html, "lxml").stripped_strings)
    now = utc_now()

    out: list[IndexPoint] = []
    index_labels = [
        "NSE ALL SHARE INDEX",
        "NSE 20 SHARE INDEX",
        "NSE 25 SHARE INDEX",
        "NASI",
        "NSE20",
        "NSE25",
    ]
    for label in index_labels:
        row = _index_point_from_text(target_date, now, label, text, "nse_market_stats")
        if not row:
            continue
        if row.index_name == "NSE20SHAREINDEX":
            row.index_name = "NSE20"
        elif row.index_name == "NSE25SHAREINDEX":
            row.index_name = "NSE25"
        elif row.index_name == "NSE20":
            row.index_name = "NSE20"
        elif row.index_name == "NSE25":
            row.index_name = "NSE25"
        elif row.index_name != "NASI":
            continue

        if any(existing.index_name == row.index_name for existing in out):
            continue
        out.append(row)
    return out


async def fetch_fx_erapi(target_date) -> list[FxPoint]:
    url = "https://open.er-api.com/v6/latest/KES"
    now = utc_now()
    text = await _http_get(url, timeout=20, retries=2, backoff_base=2.0, rate_limit_rps=0.3, cache_ttl_seconds=300)
    try:
        import json

        payload = json.loads(text)
    except Exception as exc:  # noqa: PERF203
        raise RuntimeError(f"parse_error: {exc}") from exc

    rates = payload.get("rates", {}) if isinstance(payload, dict) else {}
    out: list[FxPoint] = []

    for pair, target in [("KES/USD", "USD"), ("KES/EUR", "EUR")]:
        rate = rates.get(target)
        if rate is None:
            continue
        out.append(
            FxPoint(
                date=target_date,
                pair=pair,
                rate=float(rate),
                source_id="erapi",
                fetched_at=now,
                raw_payload={"provider": payload.get("provider") if isinstance(payload, dict) else "unknown"},
            )
        )

    return out


async def fetch_headlines_mystocks(target_date) -> list[HeadlinePoint]:
    html = await _http_get(f"{MYSTOCKS_BASE}/")
    soup = BeautifulSoup(html, "lxml")
    now = utc_now()

    out: list[HeadlinePoint] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not href or not title:
            continue
        if len(title) < 20:
            continue
        url = httpx.URL(f"{MYSTOCKS_BASE}").join(href)
        u = str(url)
        if u in seen:
            continue
        seen.add(u)

        out.append(
            HeadlinePoint(
                date=target_date,
                source_id="mystocks_news",
                headline=title,
                url=u,
                published_at=None,
                fetched_at=now,
            )
        )
        if len(out) >= 20:
            break

    return out


async def fetch_headlines_standard_rss(target_date) -> list[HeadlinePoint]:
    return await _fetch_headlines_rss(target_date, "standard_rss", STANDARD_BUSINESS_RSS_URL)


async def fetch_headlines_google_news_ke(target_date) -> list[HeadlinePoint]:
    return await _fetch_headlines_rss(target_date, "google_news_ke", GOOGLE_NEWS_KE_RSS_URL)


async def fetch_headlines_bbc_business_rss(target_date) -> list[HeadlinePoint]:
    return await _fetch_headlines_rss(target_date, "bbc_business_rss", BBC_BUSINESS_RSS_URL)


async def fetch_headlines_business_daily_html(target_date, alias_map: dict[str, set[str]]) -> list[HeadlinePoint]:
    html = await _http_get(
        BUSINESS_DAILY_HTML_URL,
        timeout=30,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.25,
    )
    return _extract_headlines_html(
        html=html,
        base_url=BUSINESS_DAILY_HTML_URL,
        source_id="business_daily_html",
        target_date=target_date,
        alias_map=alias_map,
        trust_rank=4,
        relevance_base=0.65,
    )


async def fetch_headlines_the_star_html(target_date, alias_map: dict[str, set[str]]) -> list[HeadlinePoint]:
    html = await _http_get(
        THE_STAR_BUSINESS_HTML_URL,
        timeout=30,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.25,
    )
    return _extract_headlines_html(
        html=html,
        base_url=THE_STAR_BUSINESS_HTML_URL,
        source_id="the_star_html",
        target_date=target_date,
        alias_map=alias_map,
        trust_rank=3,
        relevance_base=0.6,
    )


async def fetch_headlines_standard_business_html(target_date, alias_map: dict[str, set[str]]) -> list[HeadlinePoint]:
    html = await _http_get(
        STANDARD_BUSINESS_HTML_URL,
        timeout=30,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.25,
    )
    return _extract_headlines_html(
        html=html,
        base_url=STANDARD_BUSINESS_HTML_URL,
        source_id="standard_business_html",
        target_date=target_date,
        alias_map=alias_map,
        trust_rank=4,
        relevance_base=0.65,
    )
    item_cap = max_items if isinstance(max_items, int) and max_items > 0 else max(1, int(settings.AGENT_A_NEWS_MAX_ITEMS_PER_SOURCE))
