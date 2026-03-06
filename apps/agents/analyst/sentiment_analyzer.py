from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SentimentSignal:
    ticker: str
    sentiment_signal: str  # bullish|bearish|neutral|insufficient
    bullish_pct: float
    bearish_pct: float
    mention_count: int
    wow_delta: float | None
    momentum_state: str  # improving|deteriorating|stable|unknown


def analyze_sentiment_signal(*, ticker: str, row: dict | None) -> SentimentSignal:
    if row is None:
        return SentimentSignal(
            ticker=ticker,
            sentiment_signal="insufficient",
            bullish_pct=0.0,
            bearish_pct=0.0,
            mention_count=0,
            wow_delta=None,
            momentum_state="unknown",
        )

    mention_count = int(row.get("mentions_count") or 0)
    bullish_pct = float(row.get("bullish_pct") or 0.0)
    bearish_pct = float(row.get("bearish_pct") or 0.0)
    wow_delta = float(row.get("wow_delta")) if row.get("wow_delta") is not None else None

    if mention_count < 5:
        signal = "insufficient"
    elif bullish_pct > 55.0:
        signal = "bullish"
    elif bearish_pct > 55.0:
        signal = "bearish"
    else:
        signal = "neutral"

    momentum_state = "stable"
    if wow_delta is None:
        momentum_state = "unknown"
    elif wow_delta > 10.0:
        momentum_state = "improving"
        if signal == "neutral":
            signal = "bullish"
    elif wow_delta < -10.0:
        momentum_state = "deteriorating"
        if signal == "neutral":
            signal = "bearish"

    return SentimentSignal(
        ticker=ticker,
        sentiment_signal=signal,
        bullish_pct=round(bullish_pct, 3),
        bearish_pct=round(bearish_pct, 3),
        mention_count=mention_count,
        wow_delta=round(wow_delta, 3) if wow_delta is not None else None,
        momentum_state=momentum_state,
    )
