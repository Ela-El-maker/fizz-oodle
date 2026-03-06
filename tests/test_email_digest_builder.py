from __future__ import annotations

from apps.reporting.email_digest import builder


def test_collect_explainers_detects_known_terms() -> None:
    rows = builder._collect_explainers(
        texts=["Risk-off sentiment rose as Brent oil moved higher and yield pressure increased."],
        enabled=True,
    )
    terms = {row["term"] for row in rows}
    assert "Risk-Off" in terms
    assert "Brent" in terms
    assert "Yield" in terms


def test_collect_explainers_disabled_returns_empty() -> None:
    rows = builder._collect_explainers(texts=["fed and liquidity"], enabled=False)
    assert rows == []


def test_dedupe_links_keeps_first_unique_urls() -> None:
    links = [
        {"label": "A", "url": "https://a.example"},
        {"label": "A2", "url": "https://a.example"},
        {"label": "B", "url": "https://b.example"},
    ]
    out = builder._dedupe_links(links, limit=10)
    assert len(out) == 2
    assert out[0]["url"] == "https://a.example"
    assert out[1]["url"] == "https://b.example"
