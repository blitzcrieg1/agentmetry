"""Map AgentAudit canonical events to Elastic Common Schema (ECS) documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_timestamp(ts: str) -> str:
    if not ts:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return ts.replace("+00:00", "Z") if ts.endswith("+00:00") else ts


def _event_category(action_type: str) -> list[str]:
    if action_type in ("tool_called", "session_start", "session_end"):
        return ["process"]
    if action_type == "config_change":
        return ["configuration"]
    if action_type.startswith("approval"):
        return ["iam"]
    return ["process"]


def canonical_to_ecs(canonical: dict[str, Any]) -> dict[str, Any]:
    """Best-effort ECS 8.x field mapping; full canonical nested under agentaudit."""
    action = canonical.get("action") or {}
    actor = canonical.get("actor") or {}
    tool = canonical.get("tool") or {}
    model = canonical.get("model") or {}
    agent = canonical.get("agent") or {}

    action_type = str(action.get("type") or "")
    outcome = str(action.get("outcome") or "")

    doc: dict[str, Any] = {
        "@timestamp": _parse_timestamp(str(canonical.get("timestamp_utc") or "")),
        "event": {
            "id": canonical.get("event_id"),
            "kind": "event",
            "category": _event_category(action_type),
            "type": ["info"],
            "action": action_type,
            "outcome": outcome,
            "reason": action.get("reason") or "",
            "sequence": canonical.get("seq"),
        },
        "host": {"name": canonical.get("host_id")},
        "user": {
            "id": actor.get("id"),
            "roles": [actor.get("role")] if actor.get("role") else [],
        },
        "trace": {"id": canonical.get("correlation_id")},
        "session": {"id": canonical.get("session_id")},
        "observer": {
            "type": "agent-audit",
            "vendor": "blackbox",
            "product": "AgentAudit",
        },
        "agent": {
            "name": agent.get("name"),
            "version": canonical.get("schema_version"),
        },
        "agentaudit": canonical,
    }

    if tool:
        doc["tool"] = {
            "name": tool.get("name"),
            "type": tool.get("qualified"),
        }
        doc["service"] = {"name": tool.get("server")}

    if model.get("id"):
        doc["gen_ai"] = {
            "request": {
                "model": model.get("id"),
            },
            "system": model.get("provider"),
        }

    if outcome == "denied":
        doc["event"]["type"] = ["denied"]

    return doc
