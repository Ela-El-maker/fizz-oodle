from __future__ import annotations

from types import SimpleNamespace

from apps.agents.announcements.pipeline import _is_high_impact_alert, derive_announcements_status
from apps.agents.announcements import registry
from apps.agents.announcements import pipeline
from apps.agents.announcements.registry import get_all_source_configs


def test_status_partial_when_core_source_fails() -> None:
    status = derive_announcements_status(
        core_failures=1,
        source_failures=1,
        source_successes=2,
        new_alert_count=0,
        email_sent=False,
    )
    assert status == "partial"


def test_status_success_when_only_secondary_sources_fail() -> None:
    status = derive_announcements_status(
        core_failures=0,
        source_failures=2,
        source_successes=2,
        new_alert_count=0,
        email_sent=False,
    )
    assert status == "success"


def test_status_fail_when_alert_email_fails() -> None:
    status = derive_announcements_status(
        core_failures=0,
        source_failures=0,
        source_successes=1,
        new_alert_count=2,
        email_sent=False,
    )
    assert status == "fail"


def test_stable_only_contract_marks_cma_non_core_and_standard_as_rss() -> None:
    sources = {s.source_id: s for s in get_all_source_configs()}

    assert sources["nse_official"].required_for_success is True
    assert sources["company_ir_pages"].required_for_success is True

    assert sources["cma_market_announcements"].enabled_by_default is False
    assert sources["cma_market_announcements"].required_for_success is False
    assert sources["cma_market_announcements"].tier == "secondary"
    assert sources["cma_notices"].enabled_by_default is False

    assert sources["standard_business"].parser == "rss_feed.collect"


def test_explicit_all_enables_all_sources(monkeypatch) -> None:
    monkeypatch.setattr(registry.settings, "ENABLED_ANNOUNCEMENT_SOURCES", "all")
    selected = registry.get_source_configs()
    all_cfg = registry.get_all_source_configs()
    assert len(selected) == len(all_cfg)


def test_runtime_overrides_can_disable_source_and_tune_rate(monkeypatch) -> None:
    monkeypatch.setattr(registry.settings, "ENABLED_ANNOUNCEMENT_SOURCES", "")

    def fake_runtime(_agent: str, *, force_refresh: bool = False):  # noqa: ARG001
        return {
            "sources": {
                "standard_business": {"enabled": False},
                "nse_official": {"rate_limit_multiplier": 0.5},
            }
        }

    monkeypatch.setattr(registry, "get_agent_overrides_sync", fake_runtime)
    selected = {cfg.source_id: cfg for cfg in registry.get_source_configs()}
    assert "standard_business" not in selected
    assert "nse_official" in selected
    assert selected["nse_official"].rate_limit_rps == 0.1


def test_high_impact_alert_gate_for_global_scope(monkeypatch) -> None:
    monkeypatch.setattr(pipeline.settings, "EMAIL_ALERTS_KENYA_IMPACT_THRESHOLD", 60)
    row = SimpleNamespace(
        raw_payload={"scope": "global_outside", "kenya_impact_score": 64},
        announcement_type="other",
        type_confidence=0.3,
    )
    assert _is_high_impact_alert(row) is True


def test_high_impact_alert_gate_for_kenya_core_requires_type_and_confidence(monkeypatch) -> None:
    monkeypatch.setattr(pipeline.settings, "ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD", 0.7)
    row = SimpleNamespace(
        raw_payload={"scope": "kenya_core", "severity": "high"},
        announcement_type="dividend",
        type_confidence=0.82,
    )
    assert _is_high_impact_alert(row) is True

    low_conf = SimpleNamespace(
        raw_payload={"scope": "kenya_core", "severity": "high"},
        announcement_type="dividend",
        type_confidence=0.4,
    )
    assert _is_high_impact_alert(low_conf) is False
