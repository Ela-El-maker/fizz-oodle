from __future__ import annotations

import pytest

from apps.agents.briefing import llm_brief


@pytest.mark.asyncio
async def test_generate_market_brief_fallback_when_llm_off(monkeypatch) -> None:
    monkeypatch.setattr(llm_brief.settings, "LLM_MODE", "off")
    brief, rendered = await llm_brief.generate_market_brief(
        {
            "market_breadth": {"advancers_count": 7, "decliners_count": 5},
            "nasi": {"value": 210.0, "pct_change": 0.6},
            "top_movers": [{"ticker": "SCOM", "pct_change": 1.4}],
        }
    )
    assert brief.llm_used is False
    assert brief.llm_error == "llm_disabled"
    assert "SCOM" in rendered


@pytest.mark.asyncio
async def test_generate_market_brief_uses_api_json(monkeypatch) -> None:
    monkeypatch.setattr(llm_brief.settings, "LLM_MODE", "api")
    monkeypatch.setattr(llm_brief.settings, "LLM_API_KEY", "x")
    monkeypatch.setattr(llm_brief.settings, "LLM_API_BASE_URL", "https://example.invalid/v1")

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{\"market_pulse\":\"Tone improving\",'
                                '\"drivers\":[\"Breadth\",\"Index\"],'
                                '\"unusual_signals\":[\"Volume concentration\"],'
                                '\"narrative_interpretation\":\"Risk-on pockets visible\",'
                                '\"confidence_level\":\"high\",'
                                '\"confidence_score\":0.84,'
                                '\"confidence_reason\":\"strong_consensus\",'
                                '\"model\":\"qwen\",\"provider\":\"nvidia\"}'
                            )
                        }
                    }
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(llm_brief.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    brief, rendered = await llm_brief.generate_market_brief({"market_breadth": {}, "top_movers": []})
    assert brief.llm_used is True
    assert brief.confidence_level == "high"
    assert "Tone improving" in rendered
