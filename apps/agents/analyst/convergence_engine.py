from __future__ import annotations

from dataclasses import dataclass

from apps.agents.analyst.announcement_analyzer import AnnouncementSignal
from apps.agents.analyst.price_analyzer import PriceSignal
from apps.agents.analyst.sentiment_analyzer import SentimentSignal


@dataclass(slots=True)
class ConvergenceResult:
    ticker: str
    direction: str  # bullish|bearish|neutral
    convergence_score: int
    strength: int
    confidence_pct: float
    anomalies: list[str]
    signal_map: dict[str, str]
    decision_trace: dict


def _map_price(signal: str) -> str:
    if signal == "up":
        return "bullish"
    if signal == "down":
        return "bearish"
    if signal in {"flat", "volatile", "none"}:
        return "neutral"
    return "neutral"


def _map_announcement(signal: str) -> str:
    if signal == "positive":
        return "bullish"
    if signal == "negative":
        return "bearish"
    return "neutral"


def _map_sentiment(signal: str) -> str:
    if signal in {"bullish", "bearish", "neutral"}:
        return signal
    return "excluded"


def _base_strength(bullish_signals: int, bearish_signals: int) -> tuple[int, str, int]:
    if bullish_signals == 3:
        return 3, "bullish", 8
    if bearish_signals == 3:
        return 3, "bearish", 8
    if bullish_signals == 2:
        return 2, "bullish", 5
    if bearish_signals == 2:
        return 2, "bearish", 5
    if bullish_signals == bearish_signals:
        return 1, "neutral", 3
    if bullish_signals > bearish_signals:
        return 1, "bullish", 2
    if bearish_signals > bullish_signals:
        return 1, "bearish", 2
    return 1, "neutral", 2


def _base_confidence_from_score(score: int) -> float:
    if score >= 3:
        return 80.0
    if score == 2:
        return 65.0
    return 50.0


def compute_convergence(
    *,
    ticker: str,
    price: PriceSignal,
    announcement: AnnouncementSignal,
    sentiment: SentimentSignal,
    pattern_success_rate: float | None,
) -> ConvergenceResult:
    price_dir = _map_price(price.price_signal)
    ann_dir = _map_announcement(announcement.announcement_signal)
    sent_dir = _map_sentiment(sentiment.sentiment_signal)

    counted = [price_dir, ann_dir] + ([sent_dir] if sent_dir != "excluded" else [])
    bullish_signals = sum(1 for s in counted if s == "bullish")
    bearish_signals = sum(1 for s in counted if s == "bearish")

    convergence_score, direction, strength = _base_strength(bullish_signals, bearish_signals)
    decision_steps: list[dict] = [
        {
            "step": "base_alignment",
            "bullish_signals": bullish_signals,
            "bearish_signals": bearish_signals,
            "direction": direction,
            "convergence_score": convergence_score,
            "strength": strength,
        }
    ]
    if bullish_signals == bearish_signals:
        if ann_dir in {"bullish", "bearish"} and announcement.high_severity_recent:
            direction = ann_dir
            convergence_score = 1
            strength = max(strength, 4)
            decision_steps.append(
                {
                    "step": "deterministic_tie_break",
                    "rule": "announcement_high_severity_overrides",
                    "resolved_direction": direction,
                }
            )
        elif price_dir in {"bullish", "bearish"} and sent_dir in {"bullish", "bearish"} and price_dir != sent_dir:
            direction = price_dir
            convergence_score = 1
            strength = max(strength, 3)
            decision_steps.append(
                {
                    "step": "deterministic_tie_break",
                    "rule": "price_signal_over_sentiment_signal",
                    "resolved_direction": direction,
                }
            )

    anomalies: list[str] = []

    # price/sentiment divergence override.
    if (price_dir == "bullish" and sent_dir == "bearish") or (price_dir == "bearish" and sent_dir == "bullish"):
        anomalies.append("sentiment_price_divergence")
        convergence_score = 1
        direction = "neutral"
        strength = min(strength, 3)
        decision_steps.append(
            {
                "step": "divergence_override",
                "reason": "sentiment_price_divergence",
                "direction": direction,
                "convergence_score": convergence_score,
                "strength": strength,
            }
        )

    if abs(float(price.momentum_pct or 0.0)) > 3.0 and announcement.announcement_signal == "none":
        anomalies.append("price_no_announcement")
        decision_steps.append({"step": "anomaly_flag", "reason": "price_no_announcement"})

    if announcement.high_severity_recent and price.price_signal == "flat":
        anomalies.append("announcement_no_reaction")
        decision_steps.append({"step": "anomaly_flag", "reason": "announcement_no_reaction"})

    # Pattern adjustment from Agent E feedback.
    if pattern_success_rate is not None:
        if pattern_success_rate > 0.75 and direction in {"bullish", "bearish"}:
            strength += 1
            decision_steps.append(
                {
                    "step": "pattern_adjustment",
                    "reason": "high_pattern_success_rate",
                    "pattern_success_rate": round(pattern_success_rate, 4),
                    "strength_delta": 1,
                }
            )
        elif pattern_success_rate < 0.40:
            strength -= 1
            decision_steps.append(
                {
                    "step": "pattern_adjustment",
                    "reason": "low_pattern_success_rate",
                    "pattern_success_rate": round(pattern_success_rate, 4),
                    "strength_delta": -1,
                }
            )

    strength = max(1, min(10, strength))

    confidence = _base_confidence_from_score(convergence_score)
    if convergence_score == 3:
        confidence += 5.0
    if pattern_success_rate is not None and pattern_success_rate > 0.75 and direction in {"bullish", "bearish"}:
        confidence += 3.0
    if sentiment.mention_count > 50:
        confidence += 3.0
    if sentiment.mention_count < 5:
        confidence -= 10.0

    contributing = sum(1 for s in [price_dir, ann_dir, sent_dir] if s in {"bullish", "bearish", "neutral"})
    if contributing <= 1:
        confidence -= 8.0

    if anomalies:
        confidence -= 10.0

    if price.volatility_pct is not None and price.volatility_pct > 3.0:
        confidence -= 5.0

    confidence = max(0.0, min(95.0, confidence))
    decision_steps.append(
        {
            "step": "confidence_finalize",
            "confidence_pct": round(confidence, 2),
            "anomaly_count": len(anomalies),
            "contributing_signals": contributing,
        }
    )

    return ConvergenceResult(
        ticker=ticker,
        direction=direction,
        convergence_score=convergence_score,
        strength=strength,
        confidence_pct=round(confidence, 2),
        anomalies=anomalies,
        signal_map={
            "price": price_dir,
            "announcement": ann_dir,
            "sentiment": sent_dir,
        },
        decision_trace={
            "ticker": ticker,
            "inputs": {
                "price": price.price_signal,
                "announcement": announcement.announcement_signal,
                "sentiment": sentiment.sentiment_signal,
                "pattern_success_rate": round(pattern_success_rate, 4) if pattern_success_rate is not None else None,
            },
            "steps": decision_steps,
            "final": {
                "direction": direction,
                "convergence_score": convergence_score,
                "strength": strength,
                "confidence_pct": round(confidence, 2),
                "anomalies": anomalies,
            },
        },
    )
