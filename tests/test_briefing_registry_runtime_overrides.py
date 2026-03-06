from __future__ import annotations

from apps.agents.briefing import registry


def test_runtime_overrides_apply_to_briefing_source_and_channel_order(monkeypatch) -> None:
    def fake_runtime(_agent: str, *, force_refresh: bool = False):  # noqa: ARG001
        return {
            "sources": {
                "mystocks_news": {"enabled": False},
                "nse_market_stats": {"rate_limit_multiplier": 0.5},
            },
            "channel_order": {"news": ["standard_rss", "google_news_ke", "mystocks_news"]},
        }

    monkeypatch.setattr(registry, "get_agent_overrides_sync", fake_runtime)
    source_cfg = registry.get_briefing_source_configs()
    channel_order = registry.get_channel_order()
    assert source_cfg["mystocks_news"].enabled_by_default is False
    assert source_cfg["nse_market_stats"].rate_limit_rps == 0.1
    assert channel_order["news"][0] == "standard_rss"

