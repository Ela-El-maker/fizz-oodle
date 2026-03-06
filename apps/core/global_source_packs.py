from __future__ import annotations

GLOBAL_MARKETS_THEME_SOURCE_IDS: set[str] = {
    "eia_oil_rss",
    "eia_today_in_energy",
    "eia_press_releases",
    "global_oil_news_rss",
    "global_usd_macro_rss",
    "global_ai_platforms_rss",
    "global_bonds_yields_rss",
    "global_earnings_dividends_rss",
    "global_equities_trading_rss",
    "world_bank_commodity_markets",
    "fred_dollar_index_broad",
    "google_research_blog",
    "google_deepmind_blog",
    "anthropic_news",
    "openai_news",
    "reuters_business_global",
    "nasdaq_global_indexes",
    "investing_world_indices",
    "eia_oil_theme_rss",
    "global_oil_theme_rss",
    "global_usd_theme_rss",
    "global_ai_theme_rss",
    "global_bonds_theme_rss",
    "global_earnings_dividends_theme_rss",
    "global_equities_trading_theme_rss",
}

GLOBAL_EXTRAS_SOURCE_IDS: set[str] = {
    "durovscode_site",
    "investing_major_indices",
    "theonlinekenyan_feed",
    "infoworld_feed",
}


def source_allowed_by_pack(
    *,
    source_id: str,
    enable_theme_pack: bool,
    enable_extras_pack: bool,
) -> bool:
    sid = (source_id or "").strip().lower()
    if sid in GLOBAL_MARKETS_THEME_SOURCE_IDS and not enable_theme_pack:
        return False
    if sid in GLOBAL_EXTRAS_SOURCE_IDS and not enable_extras_pack:
        return False
    return True
