"""Live detection — correlate as events arrive, not only when someone asks.

The rule engine is a pure function over a session's events. That is fine for a
forensic query, but a detection nobody sees is not a control: until this module
existed, a `credential-exfil` finding only appeared if an operator happened to
open that session in the dashboard. Nothing streamed, nothing reached a SIEM,
nothing alerted.

This keeps a bounded in-memory window of each live session, re-runs the rules on
every ingested event, and returns only detections that are *new* for that
session — so a firing rule is emitted once, as a canonical event, down the same
sinks as everything else.

State is in-memory and per-process: it is a live tripwire, not the system of
record. The JSONL trail remains authoritative, and
`GET /audit/detections/{id}` still recomputes from it, so a restart loses
alerting continuity but never loses a detection.
"""

from __future__ import annotations

import socket
import uuid
from collections import OrderedDict
from typing import Any

from .engine import run_detections
from .models import Detection

_HOST_ID = socket.gethostname()

# Bounded so a long-running server cannot grow without limit.
_MAX_SESSIONS = 256
_MAX_EVENTS_PER_SESSION = 500

# correlation_id -> events seen this session (ordered, most recent last)
_sessions: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
# correlation_id -> rule_ids already emitted, so a rule alerts once per session
_emitted: OrderedDict[str, set[str]] = OrderedDict()


def reset_live_state() -> None:
    """Test helper — clear the in-memory session windows."""
    _sessions.clear()
    _emitted.clear()


def _touch(corr: str) -> None:
    """LRU: evict the least-recently-used session once we exceed the cap."""
    for store in (_sessions, _emitted):
        store.move_to_end(corr, last=True)
    while len(_sessions) > _MAX_SESSIONS:
        old, _ = _sessions.popitem(last=False)
        _emitted.pop(old, None)


def observe(canonical: dict[str, Any]) -> list[Detection]:
    """Record an event and return detections that are NEW for its session."""
    corr = str(canonical.get("correlation_id") or "")
    if not corr:
        return []

    events = _sessions.setdefault(corr, [])
    seen = _emitted.setdefault(corr, set())
    events.append(canonical)
    if len(events) > _MAX_EVENTS_PER_SESSION:
        del events[:-_MAX_EVENTS_PER_SESSION]
    _touch(corr)

    fresh: list[Detection] = []
    for detection in run_detections(events):
        if detection.rule_id in seen:
            continue
        seen.add(detection.rule_id)
        fresh.append(detection)
    return fresh


def build_detection_event(detection: Detection, source_event: dict[str, Any]) -> dict[str, Any]:
    """Wrap a Detection as a canonical event so it flows to every sink.

    `action.outcome` carries the severity: a SIEM can alert on
    `action.type:detection AND action.outcome:critical` without understanding
    Agentmetry's rule vocabulary.
    """
    source = source_event.get("source")
    agent = source_event.get("agent")
    return {
        "schema_version": source_event.get("schema_version", "1.1.0"),
        "event_id": str(uuid.uuid4()),
        "session_id": source_event.get("session_id", ""),
        "correlation_id": detection.correlation_id or source_event.get("correlation_id", ""),
        "timestamp_utc": source_event.get("timestamp_utc", ""),
        "host_id": _HOST_ID,
        "source_topic": f"detection/{detection.rule_id}",
        "source": source if isinstance(source, dict) else {"tier": "detection", "app": "agentmetry"},
        "initiator": source_event.get("initiator", {}),
        "actor": source_event.get("actor", {}),
        "action": {
            "type": "detection",
            "outcome": detection.severity,
            "reason": detection.summary,
        },
        "agent": agent if isinstance(agent, dict) else {"name": "agentmetry"},
        "detection": detection.as_dict(),
    }
