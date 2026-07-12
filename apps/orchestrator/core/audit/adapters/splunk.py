"""Splunk HEC envelope for AgentAudit canonical events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _epoch_seconds(ts: str) -> float:
    if not ts:
        return datetime.now(timezone.utc).timestamp()
    normalized = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


def canonical_to_hec_event(
    canonical: dict[str, Any],
    *,
    index: str,
    sourcetype: str,
    source: str = "AgentAudit",
) -> dict[str, Any]:
    action = canonical.get("action") or {}
    return {
        "time": _epoch_seconds(str(canonical.get("timestamp_utc") or "")),
        "host": canonical.get("host_id"),
        "source": source,
        "sourcetype": sourcetype,
        "index": index,
        "fields": {
            "action_type": action.get("type"),
            "action_outcome": action.get("outcome"),
            "correlation_id": canonical.get("correlation_id"),
            "actor_id": (canonical.get("actor") or {}).get("id"),
        },
        "event": canonical,
    }
