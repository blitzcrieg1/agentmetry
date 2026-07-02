"""Helpers for accumulating LLM token usage in graph state."""

from __future__ import annotations

from typing import Any

from core.llm.types import LLMResult


def merge_llm_usage(state: dict[str, Any], llm: LLMResult) -> dict[str, Any]:
    return {
        "input_tokens": state.get("input_tokens", 0) + llm.usage.input_tokens,
        "output_tokens": state.get("output_tokens", 0) + llm.usage.output_tokens,
        "cost": state.get("cost", 0.0) + llm.usage.cost,
    }
