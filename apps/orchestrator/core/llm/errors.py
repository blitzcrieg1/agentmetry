"""LLM errors surfaced to callers instead of silent mock fallback."""

from __future__ import annotations


class LLMDegradedError(Exception):
    """Raised when the configured LLM provider is unavailable (e.g. rate limited)."""

    def __init__(self, reason: str, retry_after: int = 60):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after
