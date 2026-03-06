from __future__ import annotations

from apps.agents.sentiment import registry


def test_runtime_overrides_apply_to_sentiment_sources(monkeypatch) -> None:
    monkeypatch.setattr(registry.settings, "ENABLED_SENTIMENT_SOURCES", "")

    def fake_runtime(_agent: str, *, force_refresh: bool = False):  # noqa: ARG001
        return {
            "sources": {
                "standard_business_rss": {"enabled": False},
                "google_news_ke_markets": {"rate_limit_multiplier": 0.5, "max_items_per_run": 10},
            }
        }

    monkeypatch.setattr(registry, "get_agent_overrides_sync", fake_runtime)
    selected = {cfg.source_id: cfg for cfg in registry.get_source_configs()}
    assert "standard_business_rss" not in selected
    assert "google_news_ke_markets" in selected
    assert selected["google_news_ke_markets"].rate_limit_rps == 0.25
    assert selected["google_news_ke_markets"].max_items_per_run == 10

