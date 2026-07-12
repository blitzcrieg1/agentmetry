"""Per-run audit context — initiator provenance and last gated tool (schema v1.1)."""

from __future__ import annotations

from typing import Any

from core.config import settings

# thread_id → initiator block (set at run start, server-derived only)
_thread_initiators: dict[str, dict[str, str]] = {}
# thread_id → last successful tool call on this run (for approval binding)
_thread_last_tool: dict[str, dict[str, str]] = {}


def _operator_id() -> str:
    return settings.operator_id.strip() or "local"


def build_initiator(triggered_by: str) -> dict[str, str]:
    """Derive initiator from run origin. Must never trust client-supplied headers."""
    operator_id = _operator_id()
    if triggered_by == "manual":
        return {"actor_type": "human", "trigger": "manual", "operator_id": operator_id}
    if triggered_by.startswith("channel:"):
        return {"actor_type": "human", "trigger": "channel", "operator_id": operator_id}
    if triggered_by == "cron":
        return {"actor_type": "autonomous", "trigger": "cron", "operator_id": operator_id}
    if triggered_by == "vault_watch":
        return {"actor_type": "autonomous", "trigger": "vault_watch", "operator_id": operator_id}
    if triggered_by == "ingress":
        return {"actor_type": "autonomous", "trigger": "ingress", "operator_id": operator_id}
    if triggered_by == "recovery":
        return {"actor_type": "autonomous", "trigger": "recovery", "operator_id": operator_id}
    return {
        "actor_type": "autonomous",
        "trigger": triggered_by,
        "operator_id": operator_id,
    }


def actor_from_initiator(initiator: dict[str, str]) -> dict[str, str]:
    human = initiator.get("actor_type") == "human"
    return {
        "type": "user" if human else "agent",
        "id": initiator.get("operator_id") or _operator_id(),
        "role": "operator",
    }


def default_initiator() -> dict[str, str]:
    return build_initiator("manual")


def set_thread_initiator(thread_id: str, triggered_by: str) -> dict[str, str]:
    initiator = build_initiator(triggered_by)
    _thread_initiators[thread_id] = initiator
    return initiator


def get_thread_initiator(thread_id: str) -> dict[str, str] | None:
    return _thread_initiators.get(thread_id)


def resolve_initiator(
    payload: dict[str, Any], thread_id: str = ""
) -> dict[str, str]:
    """Read initiator from payload or thread cache; fallback manual human."""
    raw = payload.get("initiator")
    if isinstance(raw, dict) and raw.get("actor_type"):
        return {
            "actor_type": str(raw.get("actor_type") or "human"),
            "trigger": str(raw.get("trigger") or "manual"),
            "operator_id": str(raw.get("operator_id") or _operator_id()),
        }
    triggered_by = str(payload.get("triggered_by") or "")
    if triggered_by:
        return build_initiator(triggered_by)
    if thread_id:
        cached = _thread_initiators.get(thread_id)
        if cached:
            return cached
    return default_initiator()


def record_tool_call(thread_id: str, qualified: str, arguments_sha256: str) -> None:
    if not thread_id:
        return
    server = qualified.split(".", 1)[0] if "." in qualified else ""
    _thread_last_tool[thread_id] = {
        "tool": qualified,
        "server": server,
        "input_hash": arguments_sha256,
    }


def last_gated_action(thread_id: str) -> dict[str, str] | None:
    if not thread_id:
        return None
    action = _thread_last_tool.get(thread_id)
    if not action or not action.get("tool"):
        return None
    return dict(action)


def clear_run_context(thread_id: str) -> None:
    _thread_initiators.pop(thread_id, None)
    _thread_last_tool.pop(thread_id, None)


def audit_payload(
    thread_id: str,
    triggered_by: str | None = None,
    *,
    initiator: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Extra bus payload fields for canonical v1.1."""
    init = initiator or (
        get_thread_initiator(thread_id)
        if thread_id
        else None
    )
    if init is None and triggered_by:
        init = build_initiator(triggered_by)
    if init is None:
        init = default_initiator()
    out: dict[str, Any] = {"initiator": init}
    if triggered_by:
        out["triggered_by"] = triggered_by
    return out
