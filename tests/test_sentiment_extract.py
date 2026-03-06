from __future__ import annotations

from apps.agents.sentiment.extract import company_name_for_ticker, extract_tickers


def test_extract_tickers_from_aliases_and_symbols() -> None:
    text = "Safaricom outlook looks bullish, while KCB may face downside risk."
    tickers = extract_tickers(text)
    assert "SCOM" in tickers
    assert "KCB" in tickers


def test_extract_tickers_multi_company_names() -> None:
    text = "Equity Group Holdings and Co-op Bank were discussed with Kenya Airways."
    tickers = extract_tickers(text)
    assert "EQTY" in tickers
    assert "COOP" in tickers
    assert "KQ" in tickers


def test_company_name_for_ticker_resolves_from_universe() -> None:
    assert company_name_for_ticker("SCOM") == "Safaricom PLC"
