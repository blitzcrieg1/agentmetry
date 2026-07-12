"""Map durable outbox rows to AgentAudit canonical events (schema v1.0.0)."""

from __future__ import annotations

import socket
import uuid
from typing import Any

from core.audit.hashing import arguments_sha256
from core.bus.events import (
    DRIVER_FAILED,
    DRIVER_MOUNTED,
    RUN_APPROVAL_DENIED,
    RUN_APPROVAL_GRANTED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_TERMINATED,
    RUN_WAITING,
    TOOL_CALLED,
    TOOL_DENIED,
)
from core.config import settings

SCHEMA_VERSION = "1.0.0"

_HOST_ID = socket.gethostname()

_TOPIC_ACTION: dict[str, tuple[str, str]] = {
    RUN_STARTED: ("session_start", "success"),
    RUN_COMPLETED: ("session_end", "success"),
    RUN_FAILED: ("session_end", "error"),
    RUN_TERMINATED: ("session_end", "denied"),
    RUN_WAITING: ("approval_request", "pending"),
    RUN_APPROVAL_GRANTED: ("approval_response", "success"),
    RUN_APPROVAL_DENIED: ("approval_response", "denied"),
    TOOL_CALLED: ("tool_called", "success"),
    TOOL_DENIED: ("tool_called", "denied"),
    DRIVER_MOUNTED: ("config_change", "success"),
    DRIVER_FAILED: ("config_change", "error"),
}

_AUDIT_TOPICS = frozenset(_TOPIC_ACTION)


def _operator_id() -> str:
    return settings.operator_id.strip() or "local"


def _split_tool(qualified: str) -> tuple[str, str]:
    if "." in qualified:
        driver, name = qualified.split(".", 1)
        return driver, name
    return "", qualified


def normalize_outbox_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one outbox dict (seq, ts, topic, session_id, thread_id, payload) to canonical JSON."""
    topic = row.get("topic", "")
    if topic not in _AUDIT_TOPICS:
        return None

    payload = row.get("payload") or {}
    action_type, default_outcome = _TOPIC_ACTION[topic]
    reason = str(payload.get("reason") or payload.get("error") or "")
    outcome = default_outcome
    if topic == RUN_FAILED:
        outcome = "error"
    elif topic == TOOL_DENIED:
        outcome = "denied"

    skill = str(payload.get("skill") or payload.get("skill_name") or "")
    tool_qualified = str(payload.get("tool") or "")
    driver_name, tool_name = _split_tool(tool_qualified)

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "seq": row.get("seq"),
        "session_id": row.get("session_id") or "",
        "correlation_id": row.get("thread_id") or "",
        "timestamp_utc": row.get("ts") or "",
        "host_id": _HOST_ID,
        "source_topic": topic,
        "actor": {
            "type": "user",
            "id": _operator_id(),
            "role": "operator",
        },
        "action": {
            "type": action_type,
            "outcome": outcome,
            "reason": reason,
        },
        "agent": {
            "name": "blackbox",
            "skill_id": skill,
        },
    }

    if tool_qualified:
        args_hash = payload.get("arguments_sha256") or ""
        event["tool"] = {
            "name": tool_name or tool_qualified,
            "qualified": tool_qualified,
            "server": driver_name,
            "input_redaction": "hash",
            "input_hash": args_hash,
            "parameters_redacted": True,
        }

    if topic in (DRIVER_MOUNTED, DRIVER_FAILED):
        event["mcp"] = {
            "server_id": str(payload.get("driver") or ""),
            "tools": payload.get("tools") or [],
        }

    if topic == RUN_APPROVAL_GRANTED and payload.get("edited"):
        event["action"]["reason"] = "approved_with_edit"

    provider = settings.llm_provider.lower()
    if provider == "gemini":
        model_id = settings.gemini_model
    elif provider == "ollama":
        model_id = settings.ollama_model
    else:
        model_id = provider
    event["model"] = {"id": model_id, "provider": provider}

    return event


def normalize_arguments_for_audit(arguments: dict[str, Any]) -> str:
    """SHA-256 hex digest of tool arguments (for host publish payloads)."""
    return arguments_sha256(arguments)
