from __future__ import annotations

import asyncio

from apps.agents.sentiment.score_llm import llm_refine_sentiment
from apps.agents.sentiment.score_rules import score_text


def test_score_rules_bullish_signal() -> None:
    row = score_text("Very bullish breakout and strong results with growth ahead.")
    assert row.label == "bullish"
    assert row.score > 0
    assert row.confidence >= 0.5


def test_score_rules_bearish_signal() -> None:
    row = score_text("Profit warning and weak results suggest downside and decline.")
    assert row.label == "bearish"
    assert row.score < 0
    assert row.confidence >= 0.5


def test_score_rules_negation_dampens_and_flips() -> None:
    row = score_text("The outlook is not bullish and not good.")
    assert row.label in {"neutral", "bearish"}
    assert row.score <= 0


def test_llm_refine_disabled_mode_returns_none(monkeypatch) -> None:
    from apps.agents.sentiment import score_llm as mod

    monkeypatch.setattr(mod.settings, "LLM_MODE", "off")
    out = asyncio.run(llm_refine_sentiment("Safaricom text", "SCOM"))
    assert out is None
