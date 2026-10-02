"""Per-run audit context — initiator provenance and last gated tool (schema v1.1)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from agentmetry.core import operator_identity as oid
from agentmetry.core.config import settings

# thread_id → initiator block (set at run start, server-derived only)
_thread_initiators: dict[str, dict[str, str]] = {}
# thread_id → last successful tool call on this run (for approval binding)
_thread_last_tool: dict[str, dict[str, str]] = {}


@lru_cache(maxsize=1)
def _orchestrator_os() -> str:
    # The account the recorder runs as does not change under a running process.
    return oid.os_operator()


def resolve_operator(client_id: object = "", client_source: object = "") -> tuple[str, str]:
    """The operator id to record, and where it came from (`initiator.operator_source`).

    Every event used to say `local`, so the trail could prove a record was not
    altered and could not say who it was about (#168). In order:

    1. An id the developer configured on their side, which the hook reports as
       `configured` (`hook_configured`). The most specific statement anybody
       made.
    2. AGENTMETRY_OPERATOR_ID on this orchestrator (`orchestrator_configured`):
       an admin override, for a service account or a shared machine. It used to
       apply to no hook event at all, because every hook sent `local` and a
       client value always won.
    3. The account the hook ran as (`hook_os`). The hook runs inside the
       developer's agent, so this is the developer.
    4. An id a client sent without saying how (`client`).
    5. The account this orchestrator runs as (`orchestrator_os`). On one
       developer's machine that is the developer; under a fleet service it is
       the service account, and the label says so rather than letting it pass
       for a person.
    6. `local`, labelled `default`, when nothing resolves.

    Everything a client sends is a claim, and the `hook_` and `client` labels
    say so. The legacy `local` a hook up to 0.9.0 sends counts as not stated.
    """
    claimed = oid.stated(client_id)
    source = str(client_source or "")
    if claimed and source == oid.CONFIGURED:
        return claimed, oid.HOOK_CONFIGURED
    configured = settings.operator_id.strip()
    if configured:
        return configured, oid.ORCHESTRATOR_CONFIGURED
    if claimed:
        return claimed, oid.HOOK_OS if source == oid.OS else oid.CLIENT
    local = _orchestrator_os()
    if local:
        return local, oid.ORCHESTRATOR_OS
    return oid.LEGACY_PLACEHOLDER, oid.DEFAULT


def operator_from_payload(payload: dict[str, Any]) -> tuple[str, str]:
    """Resolve from an ingest body: its `operator` block, else `initiator.operator_id`.

    An initiator this orchestrator built already carries a recorded source, and
    re-resolving it would relabel the recorder's own answer as a client claim.
    Only internal payloads can carry one: `IngestInitiatorBody` does not declare
    `operator_source`, so pydantic drops it from anything sent over HTTP.
    """
    op = payload.get("operator")
    if isinstance(op, dict) and oid.stated(op.get("id")):
        return resolve_operator(op.get("id"), op.get("source"))
    init = payload.get("initiator")
    if isinstance(init, dict):
        recorded = str(init.get("operator_source") or "")
        if recorded in oid.RECORDED_SOURCES and oid.stated(init.get("operator_id")):
            return str(init["operator_id"]), recorded
        return resolve_operator(init.get("operator_id"), init.get("operator_source"))
    return resolve_operator()


def _operator_id() -> str:
    return resolve_operator()[0]


def build_initiator(
    triggered_by: str, operator: tuple[str, str] | None = None
) -> dict[str, str]:
    """Derive initiator from run origin. Must never trust client-supplied headers."""
    operator_id, operator_source = operator or resolve_operator()
    if triggered_by == "manual":
        actor_type, trigger = "human", "manual"
    elif triggered_by.startswith("channel:"):
        actor_type, trigger = "human", "channel"
    else:
        # cron, vault_watch, ingress, recovery, and anything unrecognised.
        actor_type, trigger = "autonomous", triggered_by
    return {
        "actor_type": actor_type,
        "trigger": trigger,
        "operator_id": operator_id,
        "operator_source": operator_source,
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
        operator_id, operator_source = operator_from_payload(payload)
        return {
            "actor_type": str(raw.get("actor_type") or "human"),
            "trigger": str(raw.get("trigger") or "manual"),
            "operator_id": operator_id,
            "operator_source": operator_source,
        }
    triggered_by = str(payload.get("triggered_by") or "")
    if triggered_by:
        return build_initiator(triggered_by, operator_from_payload(payload))
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
