"""Unified LLM client — routes to Gemini, Ollama, or mock fallback."""

from __future__ import annotations

from core.config import settings
from core.llm.degraded import llm_degraded
from core.llm.errors import LLMDegradedError
from core.llm.gemini import call_gemini
from core.llm.mock import call_mock
from core.llm.ollama import call_ollama
from core.llm.types import LLMResult


async def call_llm(
    prompt: str,
    system: str = "",
    *,
    session_id: str = "",
    node: str = "",
) -> LLMResult:
    provider = settings.llm_provider.lower()

    if provider == "gemini" and settings.gemini_api_key:
        result = await call_gemini(prompt, system, session_id=session_id, node=node)
        if result is not None:
            return result
        if llm_degraded.active:
            raise LLMDegradedError(llm_degraded.reason, llm_degraded.retry_after_seconds)

    if provider == "ollama":
        result = await call_ollama(prompt, system, session_id=session_id, node=node)
        if result is not None:
            return result

    if settings.gemini_api_key and provider != "gemini":
        result = await call_gemini(prompt, system, session_id=session_id, node=node)
        if result is not None:
            return result

    if provider == "gemini" and settings.gemini_api_key:
        raise LLMDegradedError("Gemini unavailable", llm_degraded.retry_after_seconds or 60)

    # Never let mock output masquerade as a real run: mock requires explicit opt-in.
    if provider != "mock" and not settings.allow_mock:
        raise LLMDegradedError(
            "No LLM provider available — set GEMINI_API_KEY, start Ollama, or opt in to "
            "mock output with BLACKBOX_LLM_PROVIDER=mock / BLACKBOX_ALLOW_MOCK=true",
            retry_after=0,
        )

    return await call_mock(prompt, session_id=session_id, node=node)
