"""Unified LLM client — routes to Gemini, Ollama, or mock fallback."""

from __future__ import annotations

from core.config import settings
from core.llm.gemini import call_gemini
from core.llm.ollama import call_ollama
from core.llm.mock import call_mock


async def call_llm(
    prompt: str,
    system: str = "",
    *,
    session_id: str = "",
    node: str = "",
) -> str:
    provider = settings.llm_provider.lower()

    if provider == "gemini" and settings.gemini_api_key:
        result = await call_gemini(prompt, system, session_id=session_id, node=node)
        if result is not None:
            return result

    if provider == "ollama":
        result = await call_ollama(prompt, system, session_id=session_id, node=node)
        if result is not None:
            return result

    # Auto-fallback: try Gemini if key exists but provider wasn't set
    if settings.gemini_api_key and provider != "gemini":
        result = await call_gemini(prompt, system, session_id=session_id, node=node)
        if result is not None:
            return result

    return await call_mock(prompt, session_id=session_id, node=node)
