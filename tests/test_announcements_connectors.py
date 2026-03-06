from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.agents.announcements.sources import (
    cma_market_announcements,
    cma_notices,
    company_ir,
    html_listing,
    nse_official,
    rss_feed,
    sitemap_listing,
)
from apps.agents.announcements.sources.common import parse_html_anchors
from apps.agents.announcements.types import SourceConfig

FIXTURES = Path(__file__).parent / "fixtures" / "announcements"


def _source(source_id: str, parser: str) -> SourceConfig:
    return SourceConfig(
        source_id=source_id,
        type="news",
        base_url="https://example.com/",
        enabled_by_default=True,
        parser=parser,
        timeout_secs=10,
        retries=1,
        backoff_base=2,
        rate_limit_rps=1,
        ticker_strategy="headline_regex",
    )


@pytest.mark.asyncio
async def test_nse_connector_from_fixture(monkeypatch) -> None:
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")

    async def fake_fetch(_source, _url: str) -> str:
        return html

    monkeypatch.setattr(nse_official, "fetch_with_retries", fake_fetch)
    items = await nse_official.collect(_source("nse_official", "nse_official.collect"))
    assert len(items) >= 1
    assert "dividend" in items[0].headline.lower() or "results" in items[0].headline.lower()


@pytest.mark.asyncio
async def test_cma_connector_from_fixture(monkeypatch) -> None:
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")

    async def fake_fetch(_source, _url: str) -> str:
        return html

    monkeypatch.setattr(cma_notices, "fetch_with_retries", fake_fetch)
    items = await cma_notices.collect(_source("cma_notices", "cma_notices.collect"))
    assert len(items) >= 1


@pytest.mark.asyncio
async def test_cma_market_announcements_connector_from_fixture(monkeypatch) -> None:
    html = (FIXTURES / "cma_public_notice.html").read_text(encoding="utf-8")

    async def fake_fetch(_source, _url: str) -> str:
        return html

    monkeypatch.setattr(cma_market_announcements, "fetch_with_retries", fake_fetch)
    items = await cma_market_announcements.collect(
        _source("cma_market_announcements", "cma_market_announcements.collect")
    )
    assert len(items) == 2
    assert all("public-notice" in i.url or i.url.endswith(".pdf") for i in items)


@pytest.mark.asyncio
async def test_rss_connector_from_fixture(monkeypatch) -> None:
    feed = (FIXTURES / "feed.xml").read_text(encoding="utf-8")

    async def fake_fetch(_source, _url: str) -> str:
        return feed

    monkeypatch.setattr(rss_feed, "fetch_with_retries", fake_fetch)
    items = await rss_feed.collect(_source("business_daily_markets", "rss_feed.collect"))
    assert len(items) == 2


@pytest.mark.asyncio
async def test_standard_business_rss_connector_from_fixture(monkeypatch) -> None:
    feed = (FIXTURES / "feed.xml").read_text(encoding="utf-8")

    async def fake_fetch(_source, _url: str) -> str:
        return feed

    monkeypatch.setattr(rss_feed, "fetch_with_retries", fake_fetch)
    items = await rss_feed.collect(_source("standard_business", "rss_feed.collect"))
    assert len(items) == 2
    assert all(i.source_id == "standard_business" for i in items)


@pytest.mark.asyncio
async def test_rss_connector_strict_invalid_items_are_dropped(monkeypatch) -> None:
    feed = """<?xml version='1.0' encoding='UTF-8'?>
    <rss><channel>
      <item><title>Valid title</title><link>https://example.com/one</link></item>
      <item><title></title><link>https://example.com/two</link></item>
      <item><title>No link item</title></item>
      <item><title>Bad link</title><link>javascript:void(0)</link></item>
    </channel></rss>"""

    async def fake_fetch(_source, _url: str) -> str:
        return feed

    monkeypatch.setattr(rss_feed, "fetch_with_retries", fake_fetch)
    items = await rss_feed.collect(_source("business_daily_markets", "rss_feed.collect"))
    assert len(items) == 1
    assert items[0].headline == "Valid title"


@pytest.mark.asyncio
async def test_html_connector_from_fixture(monkeypatch) -> None:
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")

    async def fake_fetch(_source, _url: str) -> str:
        return html

    monkeypatch.setattr(html_listing, "fetch_with_retries", fake_fetch)
    items = await html_listing.collect(_source("the_star_business", "html_listing.collect"))
    assert len(items) >= 1


def test_html_connector_global_outside_allows_theme_market_headlines() -> None:
    source = _source("global_market_html", "html_listing.collect")
    source.scope = "global_outside"
    source.theme = "bonds_yields"
    source.base_url = "https://example.com/"
    html = """
    <html><body>
      <a href="/story-1">Global bond yields jump as Fed outlook shifts</a>
      <a href="/story-2">Local weather update for city commuters</a>
    </body></html>
    """
    items = parse_html_anchors(source, html)
    assert len(items) == 1
    assert "bond yields" in items[0].headline.lower()


def test_html_connector_kenya_core_keeps_disclosure_gate() -> None:
    source = _source("kenya_core_html", "html_listing.collect")
    source.scope = "kenya_core"
    source.base_url = "https://example.com/"
    html = """
    <html><body>
      <a href="/story-1">Global bond yields jump as Fed outlook shifts</a>
    </body></html>
    """
    items = parse_html_anchors(source, html)
    assert items == []


@pytest.mark.asyncio
async def test_company_ir_connector(monkeypatch) -> None:
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return self

        def all(self):
            return self._rows

    class FakeSession:
        async def execute(self, _stmt):
            return FakeResult([SimpleNamespace(ticker="SCOM", name="Safaricom", ir_url="https://example.com/ir")])

    @asynccontextmanager
    async def fake_get_session():
        yield FakeSession()

    async def fake_fetch(_source, _url: str) -> str:
        return html

    monkeypatch.setattr(company_ir, "get_session", fake_get_session)
    monkeypatch.setattr(company_ir, "fetch_with_retries", fake_fetch)

    items = await company_ir.collect(_source("company_ir_pages", "company_ir.collect"))
    assert len(items) >= 1
    assert items[0].ticker_hint == "SCOM"


@pytest.mark.asyncio
async def test_sitemap_listing_connector_from_fixture(monkeypatch) -> None:
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://example.com/news/kenya-banks-rally</loc><lastmod>2026-03-05T08:00:00Z</lastmod></url>
      <url><loc>https://example.com/news/nse-turnover-rises</loc><lastmod>2026-03-05T09:00:00Z</lastmod></url>
    </urlset>"""

    async def fake_fetch(_source, _url: str) -> str:
        return xml

    monkeypatch.setattr(sitemap_listing, "fetch_with_retries", fake_fetch)
    items = await sitemap_listing.collect(_source("kenyans_sitemap_news", "sitemap_listing.collect"))
    assert len(items) == 2
    assert all(i.url.startswith("https://example.com/news/") for i in items)
