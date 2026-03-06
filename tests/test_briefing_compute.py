from __future__ import annotations

from apps.agents.briefing.compute import TickerSummary, compute_change, rank_movers
from apps.agents.briefing.normalize import parse_float, payload_hash


def test_parse_float_numeric_variants() -> None:
    assert parse_float("8.55M") == 8_550_000
    assert parse_float("1,234.50") == 1234.5
    assert parse_float("N/A") is None


def test_compute_change_and_pct() -> None:
    change, pct = compute_change(110, 100)
    assert change == 10
    assert pct == 10


def test_rank_movers() -> None:
    rows = [
        TickerSummary("A", 10, 9, 1, 11.1, 1),
        TickerSummary("B", 10, 11, -1, -9.09, 1),
        TickerSummary("C", 10, 10, 0, 0, 1),
    ]
    gainers, losers = rank_movers(rows, top_n=2)
    assert gainers[0].ticker == "A"
    assert losers[0].ticker == "B"


def test_payload_hash_stability() -> None:
    assert payload_hash("abc") == payload_hash("abc")
