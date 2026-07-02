"""Token cost estimation for LLM providers."""

from __future__ import annotations

from core.config import settings


# USD per token (Gemini 2.5 Flash — approximate)
_GEMINI_FLASH_INPUT = 0.075 / 1_000_000
_GEMINI_FLASH_OUTPUT = 0.30 / 1_000_000

_GEMINI_PRO_INPUT = 0.125 / 1_000_000
_GEMINI_PRO_OUTPUT = 0.50 / 1_000_000


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    model_lower = model.lower()
    if "pro" in model_lower:
        return input_tokens * _GEMINI_PRO_INPUT + output_tokens * _GEMINI_PRO_OUTPUT
    return input_tokens * _GEMINI_FLASH_INPUT + output_tokens * _GEMINI_FLASH_OUTPUT


def cost_from_usage(input_tokens: int, output_tokens: int) -> float:
    return estimate_cost(settings.gemini_model, input_tokens, output_tokens)


def fallback_token_estimate(text: str) -> int:
    """Word-count heuristic when API usage metadata is absent."""
    return max(len(text.split()), 1)
