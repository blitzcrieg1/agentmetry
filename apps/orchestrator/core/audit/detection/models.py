"""Data model for correlated detections (sequence rules over a session)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Severity ordering for ranking detections most-severe first.
SEVERITY_RANK: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


@dataclass
class Detection:
    """A named, ordered pattern of events — an incident, not a single event.

    `event_ids` are the canonical events that formed the pattern, in order, so
    the dashboard can link a detection back to the exact rows in the trail.
    """

    rule_id: str
    title: str
    severity: str  # critical | high | medium | low
    summary: str
    correlation_id: str
    tactic_ids: list[str] = field(default_factory=list)
    technique_ids: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    first_seen_utc: str = ""
    last_seen_utc: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "summary": self.summary,
            "correlation_id": self.correlation_id,
            "tactic_ids": self.tactic_ids,
            "technique_ids": self.technique_ids,
            "event_ids": self.event_ids,
            "first_seen_utc": self.first_seen_utc,
            "last_seen_utc": self.last_seen_utc,
        }
