from __future__ import annotations

from apps.agents.announcements.hashing import make_announcement_id, make_content_hash


def test_announcement_id_deterministic() -> None:
    a = make_announcement_id("nse_official", "https://www.nse.co.ke/a", "KCB results", "2026-03-01")
    b = make_announcement_id("nse_official", "https://www.nse.co.ke/a", "KCB results", "2026-03-01")
    assert a == b


def test_content_hash_deterministic() -> None:
    assert make_content_hash("hello") == make_content_hash("hello")
