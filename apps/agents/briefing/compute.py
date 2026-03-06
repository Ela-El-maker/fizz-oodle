from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TickerSummary:
    ticker: str
    close: float | None
    prev_close: float | None
    change: float | None
    pct_change: float | None
    volume: float | None


def compute_change(close: float | None, prev_close: float | None) -> tuple[float | None, float | None]:
    if close is None or prev_close is None:
        return None, None
    change = close - prev_close
    if prev_close == 0:
        return change, None
    pct = (change / prev_close) * 100
    return change, pct


def rank_movers(rows: list[TickerSummary], top_n: int = 8) -> tuple[list[TickerSummary], list[TickerSummary]]:
    valid = [r for r in rows if r.pct_change is not None]
    gainers = sorted(valid, key=lambda r: r.pct_change or -10**9, reverse=True)[:top_n]
    losers = sorted(valid, key=lambda r: r.pct_change or 10**9)[:top_n]
    return gainers, losers


def coverage(expected_tickers: int, captured_tickers: int, has_index: bool, fx_pairs: int) -> dict:
    return {
        "expected_tickers": expected_tickers,
        "captured_tickers": captured_tickers,
        "ticker_coverage_pct": round((captured_tickers / expected_tickers) * 100, 2) if expected_tickers else 0.0,
        "index_available": has_index,
        "fx_pairs_count": fx_pairs,
    }
