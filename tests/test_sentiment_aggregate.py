from __future__ import annotations

from datetime import date

from apps.agents.sentiment.aggregate import build_weekly_rows


def test_weekly_aggregate_computes_counts_percentages_and_wow_delta() -> None:
    mentions = [
        {
            "post_id": "p1",
            "ticker": "SCOM",
            "score": 0.6,
            "label": "bullish",
            "confidence": 0.8,
            "source_weight": 1.0,
            "source_id": "reddit_rss",
            "url": "https://example.com/1",
            "content": "bullish growth",
            "engagement": 30,
        },
        {
            "post_id": "p2",
            "ticker": "SCOM",
            "score": -0.4,
            "label": "bearish",
            "confidence": 0.7,
            "source_weight": 0.5,
            "source_id": "business_daily_rss",
            "url": "https://example.com/2",
            "content": "weak results",
            "engagement": 7,
        },
        {
            "post_id": "p3",
            "ticker": "KCB",
            "score": 0.0,
            "label": "neutral",
            "confidence": 0.6,
            "source_weight": 1.0,
            "source_id": "reddit_rss",
            "url": "https://example.com/3",
            "content": "uncertain outlook",
            "engagement": 2,
        },
    ]

    rows = build_weekly_rows(
        week_start=date(2026, 3, 2),
        mentions=mentions,
        ticker_company={"SCOM": "Safaricom", "KCB": "KCB Group"},
        prev_scores={"SCOM": 40.0},
    )

    by_ticker = {r.ticker: r for r in rows}
    scom = by_ticker["SCOM"]
    kcb = by_ticker["KCB"]

    assert scom.mentions_count == 2
    assert scom.bullish_count == 1
    assert scom.bearish_count == 1
    assert scom.bullish_pct == 50.0
    assert scom.bearish_pct == 50.0
    assert scom.wow_delta == 10.0
    assert scom.notable_quotes[0]["excerpt"] == "bullish growth"

    assert kcb.mentions_count == 1
    assert kcb.neutral_count == 1
    assert kcb.neutral_pct == 100.0
