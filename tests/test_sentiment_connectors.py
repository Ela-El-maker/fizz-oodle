from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.agents.sentiment.connectors import (
    html_discussion,
    reddit_praw,
    reddit_rss,
    rss_news,
    sitemap_news,
    x_api,
    x_dual,
    youtube_api,
)
from apps.agents.sentiment.types import SentimentSourceConfig

ROOT = Path(__file__).resolve().parents[1]


class _FakeFetchResult:
    def __init__(self, text: str, *, ok: bool = True, status_code: int = 200):
        self.ok = ok
        self.text = text
        self.status_code = status_code
        self.error_type = None
        self.error = None
        self.not_modified = False


def _source(source_id: str, parser: str, base_url: str) -> SentimentSourceConfig:
    return SentimentSourceConfig(
        source_id=source_id,
        type="rss",
        base_url=base_url,
        enabled_by_default=True,
        parser=parser,
        timeout_secs=20,
        retries=2,
        backoff_base=2.0,
        rate_limit_rps=0.5,
        weight=1.0,
        requires_auth=False,
    )


@pytest.mark.asyncio
async def test_reddit_rss_connector_parses_fixture(monkeypatch) -> None:
    xml = (ROOT / "tests/fixtures/sentiment/reddit_rss/feed.xml").read_text(encoding="utf-8")
    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(xml)

    monkeypatch.setattr(reddit_rss, "fetch_text", fake_fetch_text)
    source = _source("reddit_rss", "reddit_rss.collect", "https://www.reddit.com/r/Kenya/new/.rss")
    rows = await reddit_rss.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 2, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "reddit_rss"
    assert rows[0].canonical_url == "https://www.reddit.com/r/Kenya/comments/abc123/safaricom/"


@pytest.mark.asyncio
async def test_rss_news_connector_parses_fixture(monkeypatch) -> None:
    xml = (ROOT / "tests/fixtures/sentiment/rss_news/feed.xml").read_text(encoding="utf-8")
    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(xml)

    monkeypatch.setattr(rss_news, "fetch_text", fake_fetch_text)
    source = _source("business_daily_rss", "rss_news.collect", "https://example.com/business/rss")
    rows = await rss_news.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 2, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "business_daily_rss"
    assert rows[0].canonical_url == "https://example.com/business/kcb-results"


@pytest.mark.asyncio
async def test_standard_rss_connector_parses_fixture(monkeypatch) -> None:
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <rss><channel>
      <item>
        <title>Standard Business: NSE turnover rises</title>
        <link>https://www.standardmedia.co.ke/business/story/2001</link>
        <pubDate>Mon, 02 Mar 2026 08:00:00 +0300</pubDate>
      </item>
    </channel></rss>"""
    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(xml)

    monkeypatch.setattr(rss_news, "fetch_text", fake_fetch_text)
    source = _source("standard_business_rss", "rss_news.collect", "https://www.standardmedia.co.ke/rss/business.php")
    rows = await rss_news.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 3, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "standard_business_rss"


@pytest.mark.asyncio
async def test_google_news_rss_query_connector_parses_fixture(monkeypatch) -> None:
    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <rss><channel>
      <item>
        <title>NSE banking rally continues</title>
        <link>https://news.google.com/articles/CBMiQ2h0dHBzOi8vZXhhbXBsZS5jb20vbmV3cy0x0gEA?oc=5</link>
        <pubDate>Sun, 01 Mar 2026 18:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(xml)

    monkeypatch.setattr(rss_news, "fetch_text", fake_fetch_text)
    source = _source(
        "google_news_ke_banking",
        "rss_news.collect",
        "https://news.google.com/rss/search?q=Kenya+banks+when:7d&hl=en-KE&gl=KE&ceid=KE:en",
    )
    rows = await rss_news.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 3, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "google_news_ke_banking"


@pytest.mark.asyncio
async def test_youtube_connector_skips_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(youtube_api.settings, "YOUTUBE_API_KEY", "")
    source = _source("youtube_api", "youtube_api.collect", "https://www.googleapis.com/youtube/v3/search")
    source.requires_auth = True
    rows = await youtube_api.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 3, tzinfo=timezone.utc),
    )
    assert rows == []


@pytest.mark.asyncio
async def test_x_connector_skips_without_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(x_api.settings, "X_API_BEARER_TOKEN", "")
    source = _source("x_search_api", "x_api.collect", "https://api.x.com/2/tweets/search/recent")
    source.requires_auth = True
    source.auth_env_key = "X_API_BEARER_TOKEN"
    rows = await x_api.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 3, tzinfo=timezone.utc),
    )
    assert rows == []


@pytest.mark.asyncio
async def test_reddit_praw_connector_fallbacks_to_rss(monkeypatch) -> None:
    xml = (ROOT / "tests/fixtures/sentiment/reddit_rss/feed.xml").read_text(encoding="utf-8")

    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(xml)

    monkeypatch.setattr(reddit_rss, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(reddit_praw.settings, "REDDIT_CLIENT_ID", "")
    monkeypatch.setattr(reddit_praw.settings, "REDDIT_CLIENT_SECRET", "")
    monkeypatch.setattr(reddit_praw.settings, "REDDIT_USER_AGENT", "")
    source = _source("reddit_rss", "reddit_praw.collect", "https://www.reddit.com/r/Kenya/new/.rss")
    rows = await reddit_praw.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 2, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "reddit_rss"


@pytest.mark.asyncio
async def test_x_dual_connector_reads_x_api(monkeypatch) -> None:
    payload = (ROOT / "tests/fixtures/sentiment/x_api/search_recent.json").read_text(encoding="utf-8")

    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(payload)

    monkeypatch.setattr(x_dual, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(x_dual.settings, "X_API_BEARER_TOKEN", "token")
    source = _source("x_search_api", "x_dual.collect", "https://api.x.com/2/tweets/search/recent")
    source.requires_auth = False
    source.auth_env_key = "X_API_BEARER_TOKEN"
    rows = await x_dual.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 4, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "x_search_api"
    assert rows[0].raw_payload["engagement"] == 21


@pytest.mark.asyncio
async def test_x_dual_connector_falls_back_to_nitter(monkeypatch) -> None:
    html = (ROOT / "tests/fixtures/sentiment/x_api/nitter_search.html").read_text(encoding="utf-8")

    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(html)

    monkeypatch.setattr(x_dual, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(x_dual.settings, "X_API_BEARER_TOKEN", "")
    monkeypatch.setattr(x_dual.settings, "X_NITTER_BASE_URL", "https://nitter.net")
    source = _source("x_search_api", "x_dual.collect", "https://api.x.com/2/tweets/search/recent")
    source.requires_auth = False
    rows = await x_dual.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 4, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert "nitter.net" in (rows[0].url or "")


@pytest.mark.asyncio
async def test_youtube_connector_collects_comment_threads(monkeypatch) -> None:
    search_payload = (ROOT / "tests/fixtures/sentiment/youtube/search.json").read_text(encoding="utf-8")
    comments_payload = (ROOT / "tests/fixtures/sentiment/youtube/comment_threads.json").read_text(encoding="utf-8")

    async def fake_fetch_text(**kwargs):
        url = kwargs.get("url", "")
        if str(url).endswith("/search"):
            return _FakeFetchResult(search_payload)
        if str(url).endswith("/commentThreads"):
            return _FakeFetchResult(comments_payload)
        return _FakeFetchResult("{}", ok=False, status_code=500)

    monkeypatch.setattr(youtube_api, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(youtube_api.settings, "YOUTUBE_API_KEY", "key")
    source = _source("youtube_api", "youtube_api.collect", "https://www.googleapis.com/youtube/v3/search")
    source.requires_auth = True
    source.auth_env_key = "YOUTUBE_API_KEY"
    rows = await youtube_api.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 4, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].raw_payload["platform"] == "youtube"
    assert rows[0].raw_payload["engagement"] == 12


@pytest.mark.asyncio
async def test_html_discussion_connector_filters_by_aliases(monkeypatch) -> None:
    html = (ROOT / "tests/fixtures/sentiment/html/forum_page.html").read_text(encoding="utf-8")

    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(html)

    monkeypatch.setattr(html_discussion, "fetch_text", fake_fetch_text)
    source = _source("mystocks_forum", "html_discussion.collect", "https://live.mystocks.co.ke/discussions")
    rows = await html_discussion.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 4, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "mystocks_forum"


@pytest.mark.asyncio
async def test_html_discussion_connector_accepts_global_theme_without_ticker(monkeypatch) -> None:
    html = """
    <html><body>
      <article>
        <p>US Treasury bond yields rose sharply as Federal Reserve officials signaled tighter liquidity.</p>
      </article>
    </body></html>
    """

    async def fake_fetch_text(**_kwargs):
        return _FakeFetchResult(html)

    monkeypatch.setattr(html_discussion, "fetch_text", fake_fetch_text)
    source = _source("investing_major_indices", "html_discussion.collect", "https://www.investing.com/indices/major-indices")
    source.type = "html"
    source.scope = "global_outside"
    source.theme = "bonds_yields"
    rows = await html_discussion.collect(
        source,
        from_dt=datetime(2026, 2, 28, tzinfo=timezone.utc),
        to_dt=datetime(2026, 3, 4, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "investing_major_indices"
    assert rows[0].raw_payload.get("signal_mode") == "theme"


@pytest.mark.asyncio
async def test_sitemap_news_connector_collects_recent_urls(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    lastmod = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    root = """<?xml version='1.0' encoding='UTF-8'?>
    <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>https://example.com/news.xml</loc></sitemap>
    </sitemapindex>"""
    child = f"""<?xml version='1.0' encoding='UTF-8'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://example.com/news/kenya-oil-costs-rise</loc><lastmod>{lastmod}</lastmod></url>
    </urlset>"""

    async def fake_fetch_text(**kwargs):
        url = kwargs.get("url", "")
        return _FakeFetchResult(child if str(url).endswith("news.xml") else root)

    monkeypatch.setattr(sitemap_news, "fetch_text", fake_fetch_text)
    source = _source("pulse_ke_sitemap_news", "sitemap_news.collect", "https://example.com/sitemap.xml")
    source.type = "sitemap"
    rows = await sitemap_news.collect(
        source,
        from_dt=now - timedelta(days=1),
        to_dt=now + timedelta(days=1),
    )
    assert len(rows) == 1
    assert rows[0].source_id == "pulse_ke_sitemap_news"
