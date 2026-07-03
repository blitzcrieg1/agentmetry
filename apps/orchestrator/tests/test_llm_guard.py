"""Tests for the mock-into-ledger guard and LLM provider provenance."""

from __future__ import annotations

import pytest

from core.config import settings
from core.graphs.usage_helpers import merge_llm_usage
from core.llm.client import call_llm
from core.llm.errors import LLMDegradedError
from core.llm.types import LLMResult, LLMUsage


async def test_call_llm_raises_when_no_provider_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "allow_mock", False)

    with pytest.raises(LLMDegradedError, match="No LLM provider available"):
        await call_llm("hello")


async def test_call_llm_mock_when_provider_is_mock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "allow_mock", False)

    result = await call_llm("hello")
    assert result.provider == "mock"
    assert "[Mock LLM Response" in result.text


async def test_call_llm_mock_when_explicitly_allowed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "allow_mock", True)

    result = await call_llm("hello")
    assert result.provider == "mock"


def test_merge_llm_usage_collects_providers():
    llm = LLMResult(text="x", usage=LLMUsage(input_tokens=5, output_tokens=3, cost=0.1), provider="gemini")
    state = {"input_tokens": 1, "output_tokens": 1, "cost": 0.05, "llm_providers": ["mock"]}

    merged = merge_llm_usage(state, llm)
    assert merged["llm_providers"] == ["mock", "gemini"]
    assert merged["input_tokens"] == 6
    assert merged["cost"] == pytest.approx(0.15)

    # Same provider twice is not duplicated.
    again = merge_llm_usage({**state, **merged}, llm)
    assert again["llm_providers"] == ["mock", "gemini"]
