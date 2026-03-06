from __future__ import annotations

from datetime import date

from apps.core.chart_builder_agent_a import build_agent_a_top_movers_chart


def test_build_agent_a_top_movers_chart_writes_png_and_b64(tmp_path) -> None:
    rows = [
        {"ticker": "SCOM", "pct_change": 2.4, "volume": 1_200_000},
        {"ticker": "KCB", "pct_change": -1.2, "volume": 950_000},
        {"ticker": "EABL", "pct_change": 0.0, "volume": 500_000},
    ]
    result = build_agent_a_top_movers_chart(
        rows=rows,
        target_date=date(2026, 3, 1),
        output_dir=str(tmp_path),
        nasi_value=215.36,
        nasi_pct=0.42,
        volume_overlay=True,
        top_n=3,
    )
    assert result.generated is True
    assert result.error is None
    assert result.path is not None
    assert result.b64_png
    assert (tmp_path / "briefing_top_movers_2026-03-01.png").exists()


def test_build_agent_a_top_movers_chart_handles_empty_rows(tmp_path) -> None:
    result = build_agent_a_top_movers_chart(
        rows=[],
        target_date=date(2026, 3, 1),
        output_dir=str(tmp_path),
        nasi_value=None,
        nasi_pct=None,
        volume_overlay=False,
    )
    assert result.generated is False
    assert result.error == "no_rows"
