"""Detection engine — orders a session's events and runs the rule registry."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import SEVERITY_RANK, Detection
from .rules import HOST_REGISTRY, REGISTRY

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _event_ts(event: dict[str, Any]) -> datetime:
    ts = event.get("timestamp_utc")
    if not isinstance(ts, str):
        return _EPOCH
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except ValueError:
        return _EPOCH


def _sorted(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Stable order: timestamp, then seq/event_id to break ties deterministically.
    def _key(event: dict[str, Any]) -> tuple[datetime, int, str]:
        seq = event.get("seq")
        seq_int = seq if isinstance(seq, int) else 0
        return (_event_ts(event), seq_int, str(event.get("event_id") or ""))

    return sorted(events, key=_key)


def run_detections(events: list[dict[str, Any]]) -> list[Detection]:
    """Run every rule over one session's events, ranked most-severe first.

    `events` should be the events for a single correlation_id; ordering is
    handled here so callers can pass them straight from the trail.
    """
    ordered = _sorted(events)
    detections: list[Detection] = []
    for rule in REGISTRY:
        detections.extend(rule(ordered))
    detections.sort(key=lambda d: (SEVERITY_RANK.get(d.severity, 99), d.first_seen_utc))
    return detections


def run_host_detections(events: list[dict[str, Any]]) -> list[Detection]:
    """Run host-scoped rules over events aggregated by host_id."""
    ordered = _sorted(events)
    detections: list[Detection] = []
    for rule in HOST_REGISTRY:
        detections.extend(rule(ordered))
    detections.sort(key=lambda d: (SEVERITY_RANK.get(d.severity, 99), d.first_seen_utc))
    return detections
