"""LLM errors surfaced to callers instead of silent mock fallback."""

from __future__ import annotations


class LLMDegradedError(Exception):
    """Raised when the configured LLM provider is unavailable (e.g. rate limited)."""

    def __init__(self, reason: str, retry_after: int = 60):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class CostBudgetExceeded(Exception):
    """Raised when a run exceeds skill max_cost_per_run."""

    def __init__(self, cost: float, max_cost: float):
        self.cost = cost
        self.max_cost = max_cost
        super().__init__(f"Cost ${cost:.4f} exceeded max ${max_cost:.4f}")
