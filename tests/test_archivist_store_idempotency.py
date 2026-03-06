from __future__ import annotations

from datetime import date

from apps.agents.archivist import pipeline as archivist_pipeline
from apps.agents.archivist.render import make_archive_payload_hash


def test_archive_payload_hash_is_deterministic() -> None:
    payload = {"summary": {"patterns_upserted": 2}, "items": [{"ticker": "SCOM"}]}
    html = "<html><body>archive</body></html>"
    h1 = make_archive_payload_hash("weekly", date(2026, 3, 2), payload, html)
    h2 = make_archive_payload_hash("weekly", date(2026, 3, 2), payload, html)
    assert h1 == h2


def test_archive_payload_hash_changes_when_payload_changes() -> None:
    payload1 = {"summary": {"patterns_upserted": 2}}
    payload2 = {"summary": {"patterns_upserted": 3}}
    html = "<html><body>archive</body></html>"
    h1 = make_archive_payload_hash("weekly", date(2026, 3, 2), payload1, html)
    h2 = make_archive_payload_hash("weekly", date(2026, 3, 2), payload2, html)
    assert h1 != h2


def test_filter_sentiment_rows_weekly_is_deterministic() -> None:
    rows = [
        {"ticker": "SCOM", "week_start": "2026-02-16", "weighted_score": 0.1},
        {"ticker": "SCOM", "week_start": "2026-02-23", "weighted_score": 0.2},
        {"ticker": "EQTY", "week_start": "2026-02-23", "weighted_score": -0.1},
    ]
    selected = archivist_pipeline._filter_sentiment_rows(
        rows,
        selected_type="weekly",
        target_period=date(2026, 2, 23),
    )
    assert len(selected) == 2
    assert {x["ticker"] for x in selected} == {"SCOM", "EQTY"}
