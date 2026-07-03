"""Event envelope and topic constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Run lifecycle
RUN_STARTED = "run/started"
RUN_NODE = "run/node"
RUN_WAITING = "run/approval_required"
RUN_COMPLETED = "run/completed"
RUN_FAILED = "run/failed"
RUN_TERMINATED = "run/terminated"
ALERT_COST = "run/cost_alert"
ALERT_DRIFT = "run/drift_alert"

# High-volume, ephemeral — excluded from the outbox.
LLM_TOKEN = "llm/token"

# Vault
VAULT_FILE_CHANGED = "vault/file_changed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any]
    seq: int = 0
    session_id: str = ""   # WebSocket routing hint; empty = not for the UI
    thread_id: str = ""
    ts: str = field(default_factory=_now_iso)
