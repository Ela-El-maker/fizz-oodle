from __future__ import annotations

from types import SimpleNamespace

from apps.core.learning_engine import summarize_learning_from_runs


def test_summarize_learning_from_runs_reports_feedback_rate() -> None:
    rows = [
        SimpleNamespace(agent_name="analyst", status="success", metrics={"feedback_applied": True}),
        SimpleNamespace(agent_name="analyst", status="partial", metrics={"feedback_applied": False}),
        SimpleNamespace(agent_name="archivist", status="success", metrics={"patterns_upserted": 3, "lifecycle_updates": 1}),
        SimpleNamespace(agent_name="announcements", status="fail", metrics={}),
    ]
    summary = summarize_learning_from_runs(rows)  # type: ignore[arg-type]
    assert summary["feedback_loop"]["analyst_runs"] == 2
    assert summary["feedback_loop"]["feedback_applied_runs"] == 1
    assert summary["feedback_loop"]["feedback_applied_rate_pct"] == 50.0
    assert summary["pattern_lifecycle"]["promotions_estimate"] == 3
    assert summary["pattern_lifecycle"]["lifecycle_updates"] == 1
    assert summary["agent_scores"]["announcements"]["failure_pct"] == 100.0
