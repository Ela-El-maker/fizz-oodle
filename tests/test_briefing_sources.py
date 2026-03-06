from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from apps.agents.briefing import sources
from apps.scrape_core.sitemap import SitemapUrl

FIX = Path(__file__).parent / "fixtures" / "briefing"


@pytest.mark.asyncio
async def test_fetch_prices_mystocks_parses_rows(monkeypatch) -> None:
    stock_html = (FIX / "stock_scom.html").read_text(encoding="utf-8")

    async def fake_get(url: str, timeout: int = 30) -> str:
        return stock_html

    monkeypatch.setattr(sources, "_http_get", fake_get)
    rows = await sources.fetch_prices_mystocks(date(2026, 3, 1), ["SCOM"])
    assert len(rows) == 1
    assert rows[0].ticker == "SCOM"
    assert rows[0].close == 32.0
    assert rows[0].volume == 8_550_000


@pytest.mark.asyncio
async def test_fetch_index_and_headlines(monkeypatch) -> None:
    home_html = (FIX / "home.html").read_text(encoding="utf-8")

    async def fake_get(url: str, timeout: int = 30) -> str:
        return home_html

    monkeypatch.setattr(sources, "_http_get", fake_get)

    idx = await sources.fetch_index_mystocks(date(2026, 3, 1))
    assert len(idx) >= 1
    assert idx[0].index_name == "NASI"

    news = await sources.fetch_headlines_mystocks(date(2026, 3, 1))
    assert len(news) >= 1


@pytest.mark.asyncio
async def test_fetch_index_nse_market_stats(monkeypatch) -> None:
    stats_html = (FIX / "nse_market_statistics.html").read_text(encoding="utf-8")

    async def fake_get(url: str, timeout: int = 30) -> str:
        return stats_html

    monkeypatch.setattr(sources, "_http_get", fake_get)
    rows = await sources.fetch_index_nse_market_stats(date(2026, 3, 1))
    names = {r.index_name for r in rows}
    assert {"NASI", "NSE20", "NSE25"} <= names
    nasi = [r for r in rows if r.index_name == "NASI"][0]
    assert nasi.value == 215.36


@pytest.mark.asyncio
async def test_fetch_headlines_standard_rss(monkeypatch) -> None:
    xml = (FIX / "standard_business_rss.xml").read_text(encoding="utf-8")

    async def fake_get(url: str, timeout: int = 30) -> str:
        return xml

    monkeypatch.setattr(sources, "_http_get", fake_get)
    rows = await sources.fetch_headlines_standard_rss(date(2026, 3, 1))
    assert len(rows) == 2
    assert rows[0].source_id == "standard_rss"
    assert "standardmedia.co.ke" in rows[0].url


@pytest.mark.asyncio
async def test_fetch_headlines_google_news_rss(monkeypatch) -> None:
    xml = (FIX / "google_news_ke_rss.xml").read_text(encoding="utf-8")

    async def fake_get(url: str, timeout: int = 30) -> str:
        return xml

    monkeypatch.setattr(sources, "_http_get", fake_get)
    rows = await sources.fetch_headlines_google_news_ke(date(2026, 3, 1))
    assert len(rows) == 1
    assert rows[0].source_id == "google_news_ke"
    assert rows[0].published_at is not None


@pytest.mark.asyncio
async def test_fetch_headlines_bbc_business_rss(monkeypatch) -> None:
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Kenya banks lift dividends</title>
        <link>https://www.bbc.co.uk/business/abc</link>
        <pubDate>Mon, 01 Mar 2026 08:00:00 +0000</pubDate>
      </item>
    </channel></rss>
    """

    async def fake_get(url: str, timeout: int = 30) -> str:
        return xml

    monkeypatch.setattr(sources, "_http_get", fake_get)
    rows = await sources.fetch_headlines_bbc_business_rss(date(2026, 3, 1))
    assert len(rows) == 1
    assert rows[0].source_id == "bbc_business_rss"
    assert "bbc.co.uk" in rows[0].url


@pytest.mark.asyncio
async def test_fetch_index_nasi_resilient_fallbacks_to_mystocks(monkeypatch) -> None:
    async def bad_nse(_target_date):
        return []

    async def bad_http(url: str, timeout: int = 30, **_kwargs) -> str:
        return "<html><body>no index values</body></html>"

    async def good_mystocks(_target_date):
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        return [
            sources.IndexPoint(date(2026, 3, 1), "NASI", 210.0, 0.2, 0.2, "mystocks", now, {"m": 1}),
            sources.IndexPoint(date(2026, 3, 1), "NSE20", 3600.0, 1.0, 0.2, "mystocks", now, {"m": 2}),
        ]

    monkeypatch.setattr(sources, "fetch_index_nse_market_stats", bad_nse)
    monkeypatch.setattr(sources, "_http_get", bad_http)
    monkeypatch.setattr(sources, "fetch_index_mystocks", good_mystocks)
    rows, diag = await sources.fetch_index_nasi_resilient(date(2026, 3, 1))
    assert len(rows) >= 1
    assert diag["source_used"] == "mystocks"
    assert any(r.index_name == "NASI" for r in rows)


@pytest.mark.asyncio
async def test_fetch_fx_erapi(monkeypatch) -> None:
    class FakeFetchResult:
        ok = True
        text = '{"provider":"x","rates":{"USD":0.00775,"EUR":0.0071}}'
        status_code = 200
        error_type = None
        error = None
        not_modified = False

    async def fake_fetch_text(**_kwargs):
        return FakeFetchResult()

    monkeypatch.setattr(sources, "fetch_text", fake_fetch_text)
    rows = await sources.fetch_fx_erapi(date(2026, 3, 1))
    assert {r.pair for r in rows} == {"KES/USD", "KES/EUR"}


@pytest.mark.asyncio
async def test_fetch_headlines_sitemap_generic(monkeypatch) -> None:
    async def fake_collect(**_kwargs):
        return [
            SitemapUrl(url="https://example.com/news/kenya-banks-rally", lastmod=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            SitemapUrl(url="https://example.com/news/oil-prices-jump", lastmod=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ]

    monkeypatch.setattr(sources, "collect_sitemap_urls", fake_collect)
    rows = await sources.fetch_headlines_sitemap(
        date(2026, 3, 1),
        source_id="kenyans_sitemap_news",
        sitemap_url="https://example.com/sitemap.xml",
        max_items=10,
    )
    assert len(rows) == 2
    assert rows[0].source_id == "kenyans_sitemap_news"
