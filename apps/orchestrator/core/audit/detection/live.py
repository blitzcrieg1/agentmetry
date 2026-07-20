"""Live detection — correlate as events arrive, not only when someone asks.

The rule engine is a pure function over a session's events. That is fine for a
forensic query, but a detection nobody sees is not a control: until this module
existed, a `credential-exfil` finding only appeared if an operator happened to
open that session in the dashboard. Nothing streamed, nothing reached a SIEM,
nothing alerted.

This keeps a bounded window of each live session, re-runs the rules on every
ingested event, and returns only detections that are *new* for that session —
so a firing rule is emitted once, as a canonical event, down the same sinks as
everything else.

Live state (event windows + emitted rule IDs) is checkpointed in SQLite so an
orchestrator restart does not re-alert or lose context for active sessions.
The JSONL trail remains authoritative; `GET /audit/detections/{id}` still
recomputes from it.
"""

from __future__ import annotations

import socket
import uuid
from typing import Any

from .engine import run_detections, run_host_detections
from .live_store import get_live_store
from .models import Detection

_HOST_ID = socket.gethostname()


def reset_live_state() -> None:
    """Test helper — clear live detection checkpoint."""
    get_live_store().clear_all()


def observe(canonical: dict[str, Any]) -> list[Detection]:
    """Record an event and return detections that are NEW for its session.

    Does NOT checkpoint here. The caller must call `mark_detection_emitted` only
    after the detection is durably stored and forwarded, so a failed emit lets
    the rule fire again on the next session event instead of being lost.
    """
    corr = str(canonical.get("correlation_id") or "")
    if not corr:
        return []

    store = get_live_store()
    events = store.append_event(corr, canonical)

    fresh: list[Detection] = []
    seen_in_batch: set[str] = set()
    for detection in run_detections(events):
        # Dedup within this call (a rule may return several findings) without
        # persisting — persistence is the caller's job, post-emit.
        if detection.rule_id in seen_in_batch or store.is_emitted(corr, detection.rule_id):
            continue
        seen_in_batch.add(detection.rule_id)
        fresh.append(detection)
    return fresh


def observe_host(canonical: dict[str, Any]) -> list[Detection]:
    """Record an event in the host-level window and return new host-scoped detections."""
    host_id = str(canonical.get("host_id") or "")
    if not host_id:
        return []

    store = get_live_store()
    events = store.append_host_event(host_id, canonical)

    fresh: list[Detection] = []
    seen_in_batch: set[str] = set()
    for detection in run_host_detections(events):
        if detection.rule_id in seen_in_batch or store.is_host_emitted(host_id, detection.rule_id):
            continue
        seen_in_batch.add(detection.rule_id)
        fresh.append(detection)
    return fresh


def mark_host_detection_emitted(host_id: str, rule_id: str, emitted_at: str = "") -> None:
    """Checkpoint a host-level detection as emitted."""
    if not host_id or not rule_id:
        return
    get_live_store().mark_host_emitted(host_id, rule_id, emitted_at=emitted_at)


def mark_detection_emitted(correlation_id: str, rule_id: str, emitted_at: str = "") -> None:
    """Checkpoint a detection as emitted for its session.

    Call ONLY after the detection event is durably stored and forwarded. Marking
    is idempotent (INSERT OR IGNORE), so a re-fired detection that finally
    succeeds does not double-alert.
    """
    if not correlation_id or not rule_id:
        return
    get_live_store().mark_emitted(correlation_id, rule_id, emitted_at=emitted_at)


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
