"""Canonical events from external agent adapters (Tier B — Cursor, Claude, etc.)."""

from __future__ import annotations

import socket
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from core.audit.canonical import SCHEMA_VERSION
from core.audit.hashing import arguments_sha256
from core.audit.run_context import actor_from_initiator, build_initiator
from core.config import settings

ExternalApp = Literal["cursor", "claude", "antigravity", "mcp_proxy", "blackbox"]

KNOWN_EXTERNAL_APPS = frozenset({"cursor", "claude", "antigravity", "mcp_proxy"})

_HOST_ID = socket.gethostname()

_ACTION_MAP = {
    "session_start": ("session_start", "success"),
    "session_end": ("session_end", "success"),
    "tool_called": ("tool_called", "success"),
    "tool_denied": ("tool_called", "denied"),
    "tool_failed": ("tool_called", "error"),
    "approval_request": ("approval_request", "pending"),
    "approval_response": ("approval_response", "success"),
}


def _operator_id() -> str:
    return settings.operator_id.strip() or "local"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_tool(qualified: str) -> tuple[str, str]:
    if "." in qualified:
        driver, name = qualified.split(".", 1)
        return driver, name
    return "", qualified


def build_external_canonical(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an adapter payload into canonical v1.1 JSON."""
    source_app = str(payload.get("source_app") or "cursor").lower()
    if source_app not in KNOWN_EXTERNAL_APPS and source_app != "blackbox":
        source_app = "cursor"

    event_type = str(payload.get("event_type") or "tool_called")
    action_type, default_outcome = _ACTION_MAP.get(event_type, ("tool_called", "success"))
    outcome = str(payload.get("outcome") or default_outcome)
    reason = str(payload.get("reason") or "")

    correlation_id = str(payload.get("correlation_id") or payload.get("thread_id") or "")
    session_id = str(payload.get("session_id") or "")

    initiator_raw = payload.get("initiator")
    if isinstance(initiator_raw, dict) and initiator_raw.get("actor_type"):
        initiator = {
            "actor_type": str(initiator_raw.get("actor_type") or "human"),
            "trigger": str(initiator_raw.get("trigger") or "manual"),
            "operator_id": str(initiator_raw.get("operator_id") or _operator_id()),
        }
    else:
        trigger = str(payload.get("triggered_by") or "manual")
        initiator = build_initiator(trigger)

    tool_block = payload.get("tool") if isinstance(payload.get("tool"), dict) else {}
    tool_qualified = str(
        tool_block.get("qualified")
        or payload.get("tool_qualified")
        or payload.get("tool_name")
        or ""
    )
    driver_name, tool_name = _split_tool(tool_qualified)

    args = tool_block.get("arguments")
    if isinstance(args, dict):
        input_hash = str(tool_block.get("input_hash") or arguments_sha256(args))
    else:
        input_hash = str(tool_block.get("input_hash") or payload.get("input_hash") or "")

    skill_id = str(payload.get("skill_id") or payload.get("skill") or "")

    model_raw = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    model_provider = str(model_raw.get("provider") or source_app)
    model_id = str(model_raw.get("id") or payload.get("model_id") or source_app)

    adapter = str(payload.get("adapter") or f"{source_app}_hook")

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "correlation_id": correlation_id,
        "timestamp_utc": str(payload.get("timestamp_utc") or _utc_now()),
        "host_id": _HOST_ID,
        "source_topic": f"external/{source_app}/{event_type}",
        "source": {
            "tier": "external",
            "app": source_app,
            "adapter": adapter,
        },
        "initiator": initiator,
        "actor": actor_from_initiator(initiator),
        "action": {
            "type": action_type,
            "outcome": outcome,
            "reason": reason,
        },
        "agent": {
            "name": source_app,
            "skill_id": skill_id,
        },
        "model": {"id": model_id, "provider": model_provider},
    }

    if tool_qualified:
        server = str(tool_block.get("server") or driver_name or source_app)
        event["tool"] = {
            "name": tool_name or tool_qualified,
            "qualified": tool_qualified,
            "server": server,
            "input_redaction": "hash",
            "input_hash": input_hash,
            "parameters_redacted": True,
        }

    gated = payload.get("gated_action")
    if isinstance(gated, dict) and gated.get("tool"):
        event["gated_action"] = {
            "tool": str(gated.get("tool") or ""),
            "server": str(gated.get("server") or ""),
            "input_hash": str(gated.get("input_hash") or ""),
        }

    if payload.get("seq") is not None:
        event["seq"] = payload["seq"]

    return event
