"""Shared LLM degraded-state tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class DegradedState:
    active: bool = False
    reason: str = ""
    since: str = ""
    retry_after_seconds: int = 0

    def set_degraded(self, reason: str, retry_after: int = 60) -> None:
        self.active = True
        self.reason = reason[:200]
        self.since = datetime.now(timezone.utc).isoformat()
        self.retry_after_seconds = retry_after

    def clear(self) -> None:
        self.active = False
        self.reason = ""
        self.since = ""
        self.retry_after_seconds = 0

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "reason": self.reason,
            "since": self.since,
            "retry_after_seconds": self.retry_after_seconds,
        }


llm_degraded = DegradedState()
