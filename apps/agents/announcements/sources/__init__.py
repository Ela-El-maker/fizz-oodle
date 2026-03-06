from __future__ import annotations

from . import cma_market_announcements, cma_notices, company_ir, html_listing, nse_official, rss_feed, sitemap_listing

PARSER_REGISTRY = {
    "nse_official.collect": nse_official.collect,
    "cma_notices.collect": cma_notices.collect,
    "cma_market_announcements.collect": cma_market_announcements.collect,
    "company_ir.collect": company_ir.collect,
    "rss_feed.collect": rss_feed.collect,
    "html_listing.collect": html_listing.collect,
    "sitemap_listing.collect": sitemap_listing.collect,
}

__all__ = ["PARSER_REGISTRY"]
