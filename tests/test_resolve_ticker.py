from __future__ import annotations

from apps.agents.announcements.resolve_ticker import resolve_ticker


def test_alias_resolution_from_headline() -> None:
    assert resolve_ticker("Co-op Bank announces AGM date") == "COOP"
    assert resolve_ticker("StanChart Kenya board appointment") == "SCBK"
    assert resolve_ticker("DTB posts strong half-year results") == "DTK"
