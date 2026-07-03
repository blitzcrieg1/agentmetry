"""Shared LLM response types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


@dataclass
class LLMResult:
    text: str
    usage: LLMUsage
    provider: str = ""
