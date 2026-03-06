from __future__ import annotations

from apps.agents.announcements.resolve_ticker import resolve_company_name, resolve_ticker


def test_resolve_ticker_from_hint() -> None:
    assert resolve_ticker("Some headline", ticker_hint="SCOM") == "SCOM"


def test_resolve_ticker_from_alias_in_headline() -> None:
    ticker = resolve_ticker("Safaricom Limited declares interim dividend")
    assert ticker == "SCOM"


def test_resolve_ticker_from_company_hint() -> None:
    ticker = resolve_ticker("Board appointment", company_hint="Equity Group Holdings")
    assert ticker == "EQTY"


def test_resolve_company_name_roundtrip() -> None:
    assert resolve_company_name("KCB") == "KCB Group Ltd"
