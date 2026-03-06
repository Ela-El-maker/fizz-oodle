from __future__ import annotations

import pytest

from apps.agents.announcements import classify


@pytest.mark.asyncio
async def test_rule_classifier_maps_keywords() -> None:
    result = await classify.classify_announcement("Safaricom dividend declared", None)
    assert result.announcement_type == "dividend"
    assert 0 <= result.confidence <= 1
    assert result.severity in {"low", "medium", "high", "critical"}
    assert 0 <= result.severity_score <= 1


@pytest.mark.asyncio
async def test_llm_gating_uses_threshold(monkeypatch) -> None:
    async def fake_llm(_headline: str, _details: str | None):
        return "board_change", None, True

    monkeypatch.setattr(classify.settings, "ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(classify.settings, "LLM_MODE", "api")
    monkeypatch.setattr(classify, "_llm_fallback", fake_llm)

    def fake_rule(_text: str):
        return classify.ClassificationResult("other", 0.20)

    monkeypatch.setattr(classify, "_rule_classify", fake_rule)

    result = await classify.classify_announcement("Ambiguous statement", "")
    assert result.announcement_type == "board_change"
    assert result.llm_used is True
    assert result.llm_attempted is True
    assert result.severity in {"low", "medium", "high", "critical"}


@pytest.mark.asyncio
async def test_llm_invalid_type_falls_back_to_rule(monkeypatch) -> None:
    async def fake_llm(_headline: str, _details: str | None):
        return "not_a_valid_type", None, True

    monkeypatch.setattr(classify.settings, "ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(classify.settings, "LLM_MODE", "api")
    monkeypatch.setattr(classify, "_llm_fallback", fake_llm)

    def fake_rule(_text: str):
        return classify.ClassificationResult("other", 0.20)

    monkeypatch.setattr(classify, "_rule_classify", fake_rule)
    result = await classify.classify_announcement("Ambiguous statement", "")
    assert result.announcement_type == "other"
    assert result.llm_used is False
    assert result.llm_attempted is True


@pytest.mark.asyncio
async def test_allow_llm_false_skips_fallback(monkeypatch) -> None:
    called = {"v": False}

    async def fake_llm(_headline: str, _details: str | None):
        called["v"] = True
        return "board_change", None, True

    monkeypatch.setattr(classify.settings, "ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(classify, "_llm_fallback", fake_llm)

    def fake_rule(_text: str):
        return classify.ClassificationResult("other", 0.20)

    monkeypatch.setattr(classify, "_rule_classify", fake_rule)
    result = await classify.classify_announcement("Ambiguous statement", "", allow_llm=False)
    assert result.announcement_type == "other"
    assert result.classification_path == "rule_no_llm_budget"
    assert called["v"] is False


@pytest.mark.asyncio
async def test_llm_error_is_typed_on_rule_fallback(monkeypatch) -> None:
    async def fake_llm(_headline: str, _details: str | None):
        return None, "rate_limited", True

    monkeypatch.setattr(classify.settings, "ANNOUNCEMENT_LLM_CONFIDENCE_THRESHOLD", 0.70)
    monkeypatch.setattr(classify, "_llm_fallback", fake_llm)

    def fake_rule(_text: str):
        return classify.ClassificationResult("other", 0.20)

    monkeypatch.setattr(classify, "_rule_classify", fake_rule)
    result = await classify.classify_announcement("Ambiguous statement", "")
    assert result.announcement_type == "other"
    assert result.llm_used is False
    assert result.llm_attempted is True
    assert result.llm_error_type == "rate_limited"
    assert result.classification_path == "rule_fallback_llm_error"
