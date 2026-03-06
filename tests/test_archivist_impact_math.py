from __future__ import annotations

from datetime import date

from apps.agents.archivist import pipeline as archivist_pipeline


def test_safe_pct_handles_zero_denominator() -> None:
    assert archivist_pipeline._safe_pct(0, 0) == 0.0
    assert archivist_pipeline._safe_pct(5, 0) == 0.0


def test_safe_pct_computes_expected_value() -> None:
    assert archivist_pipeline._safe_pct(3, 4) == 75.0
    assert archivist_pipeline._safe_pct(1, 3) == 33.33


def test_grade_for_accuracy_thresholds() -> None:
    assert archivist_pipeline._grade_for_accuracy(90.0, 2) == "insufficient"
    assert archivist_pipeline._grade_for_accuracy(80.0, 5) == "excellent"
    assert archivist_pipeline._grade_for_accuracy(61.0, 5) == "good"
    assert archivist_pipeline._grade_for_accuracy(45.0, 5) == "fair"
    assert archivist_pipeline._grade_for_accuracy(10.0, 5) == "poor"


def test_monthly_sentiment_trends_builds_delta_ranked_rows() -> None:
    rows = [
        {"ticker": "SCOM", "week_start": date(2026, 2, 2).isoformat(), "weighted_score": 0.10, "confidence": 0.70},
        {"ticker": "SCOM", "week_start": date(2026, 2, 9).isoformat(), "weighted_score": 0.20, "confidence": 0.75},
        {"ticker": "EQTY", "week_start": date(2026, 2, 2).isoformat(), "weighted_score": -0.10, "confidence": 0.60},
        {"ticker": "EQTY", "week_start": date(2026, 2, 9).isoformat(), "weighted_score": -0.40, "confidence": 0.65},
    ]

    trends = archivist_pipeline._monthly_sentiment_trends(rows)
    assert len(trends) == 2
    assert trends[0]["ticker"] == "EQTY"
    assert trends[0]["delta"] == -0.3
    assert trends[1]["ticker"] == "SCOM"
    assert trends[1]["delta"] == 0.1
