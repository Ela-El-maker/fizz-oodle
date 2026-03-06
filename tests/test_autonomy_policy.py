from __future__ import annotations

from types import SimpleNamespace

from apps.core.autonomy_policy import compute_priority_score, summarize_runs


def test_compute_priority_score_uses_locked_formula() -> None:
    score = compute_priority_score(
        staleness=80.0,
        impact=70.0,
        anomaly=30.0,
        dependency_readiness=90.0,
        cost_penalty=12.0,
    )
    assert score == 56.5


def test_summarize_runs_reports_terminality_by_agent() -> None:
    rows = [
        SimpleNamespace(agent_name="briefing", status="success"),
        SimpleNamespace(agent_name="briefing", status="partial"),
        SimpleNamespace(agent_name="briefing", status="running"),
        SimpleNamespace(agent_name="announcements", status="fail"),
    ]
    summary = summarize_runs(rows)  # type: ignore[arg-type]
    assert summary["run_count_window"] == 4
    assert summary["terminal_runs_window"] == 3
    assert summary["terminality_pct"] == 75.0
    assert summary["by_agent"]["briefing"]["terminality_pct"] == 66.67
