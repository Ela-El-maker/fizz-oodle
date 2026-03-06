from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, date

from apps.agents.sentiment.types import WeeklyRow
from apps.core.config import get_settings

settings = get_settings()


def _pct(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((part / total) * 100.0, 2)


def build_weekly_rows(
    week_start: date,
    mentions: list[dict],
    ticker_company: dict[str, str],
    prev_scores: dict[str, float],
) -> list[WeeklyRow]:
    per_ticker: dict[str, list[dict]] = defaultdict(list)
    for m in mentions:
        per_ticker[str(m["ticker"]).upper()].append(m)

    rows: list[WeeklyRow] = []
    min_mentions = int(settings.SENTIMENT_MIN_MENTIONS_PER_TICKER)

    for ticker in sorted(ticker_company.keys()):
        bucket = per_ticker.get(ticker, [])
        n = len(bucket)
        label_counts = Counter(m["label"] for m in bucket)
        bull = int(label_counts.get("bullish", 0))
        bear = int(label_counts.get("bearish", 0))
        neu = int(label_counts.get("neutral", 0))

        conf_acc = 0.0
        source_counter = Counter()
        for m in bucket:
            conf = float(m["confidence"])
            conf_acc += conf
            source_counter[str(m["source_id"])] += 1

        # Normalize percentages to deterministic sum=100.00
        if n > 0:
            raw_bullish_pct = _pct(bull, n)
            raw_bearish_pct = _pct(bear, n)
            raw_neutral_pct = _pct(neu, n)
            sum_raw = raw_bullish_pct + raw_bearish_pct + raw_neutral_pct
            if sum_raw > 0:
                bullish_pct = round((raw_bullish_pct / sum_raw) * 100.0, 2)
                bearish_pct = round((raw_bearish_pct / sum_raw) * 100.0, 2)
                neutral_pct = round(100.0 - bullish_pct - bearish_pct, 2)
            else:
                bullish_pct = 0.0
                bearish_pct = 0.0
                neutral_pct = 100.0
        else:
            bullish_pct = 0.0
            bearish_pct = 0.0
            neutral_pct = 100.0

        # Keep weighted_score in [-1,1] tied to bullish-vs-bearish spread.
        weighted_score = round((bullish_pct - bearish_pct) / 100.0, 3)

        confidence = round((conf_acc / n), 3) if n > 0 else 0.2
        if n < min_mentions:
            confidence = min(confidence, 0.49)

        # Notable quote: highest-engagement mention.
        top = None
        if bucket:
            top = max(bucket, key=lambda m: float(m.get("engagement") or 0.0))
        quotes = []
        if top is not None:
            quotes = [
                {
                    "source_id": str(top.get("source_id") or ""),
                    "url": top.get("url"),
                    "excerpt": (top.get("content") or "")[:500],
                    "engagement": float(top.get("engagement") or 0.0),
                }
            ]

        wow_delta = None
        if ticker in prev_scores:
            # Week-over-week bullish percentage delta.
            wow_delta = round(bullish_pct - float(prev_scores[ticker]), 3)

        rows.append(
            WeeklyRow(
                week_start=week_start,
                ticker=ticker,
                company_name=ticker_company.get(ticker, ticker),
                mentions_count=n,
                bullish_count=bull,
                bearish_count=bear,
                neutral_count=neu if n > 0 else 0,
                bullish_pct=bullish_pct,
                bearish_pct=bearish_pct,
                neutral_pct=neutral_pct,
                weighted_score=weighted_score,
                confidence=confidence,
                top_sources=dict(source_counter),
                notable_quotes=quotes,
                wow_delta=wow_delta,
                generated_at=datetime.now(timezone.utc),
            )
        )

    return rows
