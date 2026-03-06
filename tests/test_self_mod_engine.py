from __future__ import annotations

from apps.core.self_mod_engine import build_self_mod_proposals


def test_build_self_mod_proposals_from_learning_summary() -> None:
    autonomy = {"safe_mode": False}
    learning = {
        "source_adaptation_recommendations": [
            {
                "agent_name": "announcements",
                "action": "throttle_secondary_sources",
                "reason": "failure_pct=12.50",
            }
        ]
    }
    items = build_self_mod_proposals(autonomy_state=autonomy, learning_summary=learning, healing_incidents=[])
    assert len(items) == 1
    proposal = items[0]
    assert proposal["proposal_type"] == "throttle_secondary_sources"
    assert proposal["agent_name"] == "announcements"
    assert "standard_business" in proposal["changes"]["sources"]


def test_build_self_mod_proposals_includes_safe_mode_and_incident_driven_changes() -> None:
    autonomy = {"safe_mode": True}
    learning = {"source_adaptation_recommendations": []}
    incidents = [{"failure_type": "blocked", "component": "source:reddit_rss"}]
    items = build_self_mod_proposals(autonomy_state=autonomy, learning_summary=learning, healing_incidents=incidents)
    proposal_types = {item["proposal_type"] for item in items}
    assert "safe_mode_disable_noisy_sources" in proposal_types
    assert "cooldown_unstable_source" in proposal_types

