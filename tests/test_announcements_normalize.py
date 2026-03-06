from __future__ import annotations

from apps.agents.announcements.normalize import canonicalize_url, normalize_headline, parse_datetime_to_utc


def test_canonicalize_url_strips_tracking_params_and_fragment() -> None:
    raw = "https://www.nse.co.ke/notice?id=1&utm_source=x&fbclid=abc#top"
    got = canonicalize_url(raw)
    assert got == "https://www.nse.co.ke/notice?id=1"


def test_normalize_headline_is_stable() -> None:
    assert normalize_headline("  KCB   Group — results   ") == "KCB Group - results"


def test_parse_datetime_to_utc() -> None:
    dt = parse_datetime_to_utc("Sun, 01 Mar 2026 08:00:00 +0300")
    assert dt is not None
    assert dt.tzinfo is not None
