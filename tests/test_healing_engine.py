from __future__ import annotations

from apps.core.healing_engine import action_for_failure, classify_failure


def test_classify_failure_prefers_status_code_signals() -> None:
    assert classify_failure(status_code=429, error_message="too many requests") == "rate_limited"
    assert classify_failure(status_code=403, error_message="forbidden") == "blocked"


def test_classify_failure_uses_message_patterns() -> None:
    assert classify_failure(error_message="DNS resolution failed") == "dns_error"
    assert classify_failure(error_message="database timeout") == "timeout"
    assert classify_failure(error_message="unexpected parser mismatch") == "parse_error"


def test_action_for_failure_defaults_to_safe_action() -> None:
    assert action_for_failure("llm_error") == "switch_rule_only_mode"
    assert action_for_failure("stale_run_timeout") == "mark_run_failed"
    assert action_for_failure("nonexistent") == "record_and_escalate"
