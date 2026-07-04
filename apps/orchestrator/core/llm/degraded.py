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

    def retry_elapsed(self) -> bool:
        """True once the provider's retry window has passed (RPM windows are short)."""
        if not self.active:
            return False
        if self.retry_after_seconds <= 0 or not self.since:
            return True
        since_dt = datetime.fromisoformat(self.since)
        elapsed = (datetime.now(timezone.utc) - since_dt).total_seconds()
        return elapsed >= self.retry_after_seconds

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "reason": self.reason,
            "since": self.since,
            "retry_after_seconds": self.retry_after_seconds,
        }


llm_degraded = DegradedState()
