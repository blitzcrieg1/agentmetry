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
FLYWHEEL_CAPTURE = "run/flywheel_capture"
ALERT_COST = "run/cost_alert"
ALERT_DRIFT = "run/drift_alert"

# High-volume, ephemeral — excluded from the outbox.
LLM_TOKEN = "llm/token"

# Vault
VAULT_FILE_CHANGED = "vault/file_changed"

# Interrupt vector table
INTERRUPT_RAISED = "interrupt/raised"
INTERRUPT_RESOLVED = "interrupt/resolved"

# Driver subsystem (MCP)
DRIVER_MOUNTED = "driver/mounted"
DRIVER_FAILED = "driver/failed"
TOOL_CALLED = "run/tool_called"
TOOL_DENIED = "run/tool_denied"


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
