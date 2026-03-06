from __future__ import annotations

from datetime import date

from apps.agents.analyst import features as analyst_features
from apps.agents.analyst.features import build_features
from apps.agents.analyst.rules import build_payload, build_subject
from apps.agents.analyst.types import InputsBundle, MarketMover


def _bundle(*, degraded: bool = False, archivist_feedback: dict | None = None) -> InputsBundle:
    reasons = ["briefing_missing"] if degraded else []
    return InputsBundle(
        report_type="daily",
        period_key=date(2026, 3, 1),
        market_date=date(2026, 3, 1),
        briefing={"briefing_date": "2026-03-01", "status": "sent"},
        announcements=[
            {
                "announcement_id": "a1",
                "ticker": "SCOM",
                "type": "earnings",
                "headline": "Safaricom full-year results",
                "url": "https://example.com/a1",
                "date": "2026-03-01T08:00:00+00:00",
                "source_id": "nse",
            }
        ],
        sentiment_rows=[
            {
                "ticker": "SCOM",
                "company_name": "Safaricom",
                "mentions_count": 12,
                "bullish_pct": 65.0,
                "bearish_pct": 15.0,
                "neutral_pct": 20.0,
                "weighted_score": 0.33,
                "confidence": 0.81,
                "wow_delta": 0.10,
                "notable_quotes": [],
                "top_sources": {"reddit": 8},
            }
        ],
        index_rows=[{"index_name": "NASI", "value": 120.2, "change_val": 1.1, "pct_change": 0.9, "source_id": "mystocks"}],
        fx_rows=[{"pair": "KES/USD", "rate": 0.0078, "source_id": "erapi"}],
        movers=[MarketMover("SCOM", 20.5, 2.1)],
        losers=[MarketMover("KCB", 18.2, -1.2)],
        archivist_feedback=archivist_feedback,
        degraded_reasons=reasons,
        inputs_summary={},
    )


def test_build_subject() -> None:
    assert build_subject("daily", date(2026, 3, 1)).startswith("🧾")
    assert build_subject("weekly", date(2026, 3, 2)).startswith("🧠")


def test_deterministic_payload_generation() -> None:
    bundle = _bundle(degraded=False)
    features = build_features(bundle)

    p1 = build_payload(bundle, features, min_confidence_for_strong_language=0.7)
    p2 = build_payload(bundle, features, min_confidence_for_strong_language=0.7)

    assert p1.overview == p2.overview
    assert p1.what_to_watch == p2.what_to_watch
    assert p1.degraded is False


def test_degraded_payload_flags_quality() -> None:
    bundle = _bundle(degraded=True)
    payload = build_payload(bundle, build_features(bundle), min_confidence_for_strong_language=0.7)
    assert payload.degraded is True
    assert any("degraded" in line.lower() for line in payload.data_quality)


def test_pattern_weight_cap_applies_when_feedback_coverage_is_low(monkeypatch) -> None:
    monkeypatch.setattr(analyst_features.settings, "ANALYST_PATTERN_FEEDBACK_MIN_ACTIVE_PATTERNS", 3)
    monkeypatch.setattr(analyst_features.settings, "ANALYST_PATTERN_FEEDBACK_WEIGHT_CAP", 0.6)

    bundle = _bundle(
        archivist_feedback={
            "patterns": [
                {
                    "ticker": "SCOM",
                    "status": "confirmed",
                    "accuracy_pct": 90.0,
                }
            ],
            "impacts": [],
            "archive_latest_weekly": {"updated_at": "2026-03-01T10:00:00+00:00"},
        }
    )
    features = build_features(bundle)
    top = features["signal_intelligence"]["top_convergence"][0]
    feedback = features["signal_intelligence"]["feedback"]

    assert feedback["pattern_weight_capped"] is True
    assert top["pattern_weight_capped"] is True
    assert top["pattern_success_rate_raw"] == 0.9
    assert top["pattern_success_rate"] == 0.74
    assert any(step.get("step") == "pattern_weight_cap" for step in top["decision_trace"]["steps"])
