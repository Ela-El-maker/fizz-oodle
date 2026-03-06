from __future__ import annotations

from datetime import datetime, timezone

from apps.agents.analyst.announcement_analyzer import analyze_announcement_signal
from apps.agents.analyst.convergence_engine import compute_convergence
from apps.agents.analyst.price_analyzer import analyze_price_signal
from apps.agents.analyst.sentiment_analyzer import analyze_sentiment_signal


def test_price_signal_up_and_volatile_override() -> None:
    up = analyze_price_signal(
        ticker="SCOM",
        history_rows=[
            {"date": "2026-03-01", "close": 10.0, "volume": 1000},
            {"date": "2026-03-02", "close": 10.2, "volume": 1000},
            {"date": "2026-03-03", "close": 10.4, "volume": 1200},
            {"date": "2026-03-04", "close": 10.5, "volume": 1300},
            {"date": "2026-03-05", "close": 10.6, "volume": 2000},
        ],
    )
    assert up.price_signal == "up"
    assert up.momentum_pct and up.momentum_pct > 1.0

    volatile = analyze_price_signal(
        ticker="KCB",
        history_rows=[
            {"date": "2026-03-01", "close": 10.0},
            {"date": "2026-03-02", "close": 13.0},
            {"date": "2026-03-03", "close": 9.0},
            {"date": "2026-03-04", "close": 14.0},
            {"date": "2026-03-05", "close": 8.0},
        ],
    )
    assert volatile.price_signal == "volatile"
    assert volatile.volatility_pct and volatile.volatility_pct > 2.0


def test_announcement_signal_weighting_and_high_severity_recent() -> None:
    now_utc = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    signal = analyze_announcement_signal(
        ticker="SCOM",
        now_utc=now_utc,
        rows=[
            {
                "ticker": "SCOM",
                "announcement_type": "dividend",
                "headline": "SCOM announces interim dividend",
                "first_seen_at": "2026-03-05T02:00:00+00:00",
                "severity": "high",
            },
            {
                "ticker": "SCOM",
                "announcement_type": "profit_warning",
                "headline": "SCOM warning from last month",
                "first_seen_at": "2026-02-15T08:00:00+00:00",
                "severity": "medium",
            },
        ],
    )
    assert signal.announcement_signal == "positive"
    assert signal.weighted_positive > signal.weighted_negative
    assert signal.high_severity_recent is True


def test_sentiment_thresholds_and_momentum_bias() -> None:
    insufficient = analyze_sentiment_signal(
        ticker="SCOM",
        row={"ticker": "SCOM", "mentions_count": 3, "bullish_pct": 80.0, "bearish_pct": 10.0, "wow_delta": 0.0},
    )
    assert insufficient.sentiment_signal == "insufficient"

    improving = analyze_sentiment_signal(
        ticker="SCOM",
        row={"ticker": "SCOM", "mentions_count": 30, "bullish_pct": 50.0, "bearish_pct": 40.0, "wow_delta": 12.0},
    )
    assert improving.sentiment_signal == "bullish"
    assert improving.momentum_state == "improving"


def test_convergence_detects_divergence_and_caps_confidence() -> None:
    price = analyze_price_signal(
        ticker="SCOM",
        history_rows=[
            {"date": "2026-03-01", "close": 10.0},
            {"date": "2026-03-02", "close": 10.5},
            {"date": "2026-03-03", "close": 11.0},
            {"date": "2026-03-04", "close": 11.5},
            {"date": "2026-03-05", "close": 12.0},
        ],
    )
    announcement = analyze_announcement_signal(
        ticker="SCOM",
        now_utc=datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc),
        rows=[],
    )
    sentiment = analyze_sentiment_signal(
        ticker="SCOM",
        row={"ticker": "SCOM", "mentions_count": 100, "bullish_pct": 10.0, "bearish_pct": 80.0, "wow_delta": -15.0},
    )
    conv = compute_convergence(
        ticker="SCOM",
        price=price,
        announcement=announcement,
        sentiment=sentiment,
        pattern_success_rate=0.90,
    )
    assert "sentiment_price_divergence" in conv.anomalies
    assert conv.convergence_score == 1
    assert conv.direction == "neutral"
    assert 0.0 <= conv.confidence_pct <= 95.0
    assert conv.decision_trace["final"]["direction"] == "neutral"
    assert any(step.get("step") == "divergence_override" for step in conv.decision_trace["steps"])
