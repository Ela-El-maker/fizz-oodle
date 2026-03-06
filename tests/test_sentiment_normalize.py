from __future__ import annotations

from datetime import datetime, timezone

from apps.agents.sentiment.normalize import canonicalize_url, make_post_id, normalize_text, payload_hash


def test_canonicalize_url_strips_tracking_params() -> None:
    a = canonicalize_url("https://example.com/post?id=1&utm_source=x&fbclid=abc")
    b = canonicalize_url("https://example.com/post?id=1")
    assert a == b


def test_make_post_id_is_deterministic_for_normalized_variants() -> None:
    published = datetime(2026, 3, 1, tzinfo=timezone.utc)
    p1 = make_post_id(
        source_id="reddit_rss",
        canonical_url="https://example.com/a",
        title=" Safaricom  growth ",
        content="Strong  results  and  growth",
        published_at=published,
    )
    p2 = make_post_id(
        source_id="reddit_rss",
        canonical_url="https://example.com/a",
        title="safaricom growth",
        content=normalize_text("Strong results and growth"),
        published_at=published,
    )
    assert p1 == p2


def test_payload_hash_stable() -> None:
    assert payload_hash("abc") == payload_hash("abc")
