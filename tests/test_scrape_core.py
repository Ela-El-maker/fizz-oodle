from __future__ import annotations

import asyncio

from apps.scrape_core.dedupe import canonical_url_fingerprint, content_fingerprint, normalize_canonical_url
from apps.scrape_core.retry import backoff_with_jitter, classify_error_type, should_retry
from apps.scrape_core.sitemap import collect_sitemap_urls, parse_sitemap_document


def test_normalize_canonical_url_strips_tracking_params() -> None:
    url = "https://example.com/path/?utm_source=x&b=2&a=1#frag"
    normalized = normalize_canonical_url(url)
    assert normalized == "https://example.com/path?a=1&b=2"


def test_fingerprints_are_deterministic() -> None:
    u1 = canonical_url_fingerprint("https://example.com/x?b=2&a=1")
    u2 = canonical_url_fingerprint("https://example.com/x?a=1&b=2")
    assert u1 == u2
    assert content_fingerprint("hello", "world") == content_fingerprint("hello", "world")


def test_retry_policy_behaviour() -> None:
    assert should_retry("timeout", 0, 3) is True
    assert should_retry("blocked", 0, 3) is False
    assert should_retry("rate_limited", 3, 3) is False


class _FakeExc(Exception):
    pass


def test_classify_unknown_error() -> None:
    assert classify_error_type(_FakeExc("x")) == "unknown_error"


def test_backoff_with_jitter_positive() -> None:
    value = backoff_with_jitter(2.0, 1)
    assert value > 0


def test_parse_sitemap_document_supports_urlset_and_index() -> None:
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>https://example.com/s1.xml</loc></sitemap>
      <sitemap><loc>https://example.com/s2.xml</loc></sitemap>
    </sitemapindex>"""
    rows, nested = parse_sitemap_document(xml, base_url="https://example.com/sitemap.xml")
    assert rows == []
    assert len(nested) == 2


def test_collect_sitemap_urls_walks_nested_index() -> None:
    root = """<?xml version='1.0' encoding='UTF-8'?>
    <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>https://example.com/news.xml</loc></sitemap>
    </sitemapindex>"""
    child = """<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://example.com/story-a</loc><lastmod>2026-03-05T10:00:00Z</lastmod></url>
      <url><loc>https://example.com/story-b</loc><lastmod>2026-03-06T09:00:00Z</lastmod></url>
    </urlset>"""

    async def _fake_fetch(url: str) -> str:
        if url.endswith("news.xml"):
            return child
        return root

    rows = asyncio.run(
        collect_sitemap_urls(
            root_url="https://example.com/sitemap.xml",
            fetch_xml=_fake_fetch,
            max_urls=10,
            lookback_hours=240,
        )
    )
    assert len(rows) == 2
    assert rows[0].url == "https://example.com/story-b"
