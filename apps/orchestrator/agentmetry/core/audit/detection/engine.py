"""Detection engine — orders a session's events and runs the rule registry."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import SEVERITY_RANK, Detection
from .rules import HOST_REGISTRY, REGISTRY
from .yaml_rules import build_yaml_rules

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _session_rules():
    return [*REGISTRY, *build_yaml_rules()]


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
    """Time order, falling back to the order the caller supplied.

    The tie-break used to end with `event_id`, which is a random UUID. Every
    sequence rule in this package asks "did A happen before B", so on a
    timestamp tie the answer was decided by a coin flip.

    Ties are not rare. Windows clock granularity is around 15 ms, so two tool
    calls from one agent turn routinely share a timestamp; this surfaced as a
    Windows-only CI failure where `credential-read-then-cloud-api` fired or did
    not depending on which UUID sorted first. The README claims ordering is
    enforced by position rather than co-occurrence, and a random tie-break
    quietly made that untrue.

    `sorted` is stable, so omitting the UUID preserves the input order on ties.
    Callers hand us events straight from the trail, which returns them ordered
    by `timestamp_utc` then insert id, so input order *is* arrival order: the
    best available evidence of what actually happened first.
    """
    def _key(event: dict[str, Any]) -> tuple[datetime, int]:
        seq = event.get("seq")
        seq_int = seq if isinstance(seq, int) else 0
        return (_event_ts(event), seq_int)

    return sorted(events, key=_key)


def run_detections(events: list[dict[str, Any]]) -> list[Detection]:
    """Run every rule over one session's events, ranked most-severe first.

    `events` should be the events for a single correlation_id; ordering is
    handled here so callers can pass them straight from the trail.
    """
    ordered = _sorted(events)
    detections: list[Detection] = []
    for rule in _session_rules():
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
