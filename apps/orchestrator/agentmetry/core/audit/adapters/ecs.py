"""Map Agentmetry canonical events to Elastic Common Schema (ECS) documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_timestamp(ts: str) -> str:
    if not ts:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return ts.replace("+00:00", "Z") if ts.endswith("+00:00") else ts


def _event_category(action_type: str) -> list[str]:
    """Map a canonical action type onto ECS `event.category`.

    ECS categories drive Elastic's prebuilt dashboards and detection rules, so a
    correlated finding filed under `process` disappears among the tool calls it
    was raised about. `intrusion_detection` is the category Elastic reserves for
    exactly this: an alert produced by a rule rather than an observation.

    A denied tool call is both a process event and the enforcement of a policy,
    which is why it carries two categories. ECS is explicitly multi-valued here.
    """
    if action_type == "detection":
        return ["intrusion_detection"]
    if action_type in ("tool_denied", "tool_failed"):
        return ["process", "intrusion_detection"]
    if action_type in ("tool_called", "session_start", "session_end"):
        return ["process"]
    if action_type == "config_change":
        return ["configuration"]
    if action_type.startswith("approval") or action_type == "detection_disposition":
        return ["iam"]
    return ["process"]


def _threat(canonical: dict, tool: dict, action_type: str) -> dict | None:
    """ECS `threat.*` from the ATT&CK mapping, when there is one.

    The mapping was already being computed and stored; it just never reached the
    field a SOC queries. `agentmetry.tool.mitre.technique_id` is our namespace,
    and a customer's existing ATT&CK dashboard, Navigator coverage layer and
    prebuilt detection content all join on `threat.technique.id` instead. The
    classification was correct and invisible, which reads as a shallower
    integration than the one that shipped.

    `threat.framework` is set explicitly rather than left implied. ECS provides
    that field precisely because the fieldset is not reserved to one taxonomy,
    and naming it is what stops a second framework from silently polluting an
    aggregation that does not filter on it.

    Which is why ATLAS must never be routed here. An `AML.T****` in
    `threat.technique.id` would corrupt every customer rollup that groups by
    technique without checking the framework first. Agent-directed taxonomy
    belongs under `agentmetry.tool.atlas.*`. See #47.

    Returns None rather than an empty shell when nothing was classified.
    `get_mitre_mapping` declines to guess, and an adapter that invented a value
    to fill out the document would be undoing that on the way to the sink. An
    absent `threat.technique.id` is the honest representation of "not
    classified".
    """
    # A finding carries the techniques of every event that produced it, which is
    # the more useful thing to tag: an analyst pivots from the alert, not from
    # one of the twenty tool calls underneath it. ECS keyword fields are
    # multi-valued, so the id lists map straight across. Names are not on the
    # detection block, so only ids are set here.
    if action_type == "detection":
        detection = canonical.get("detection") or {}
        tactic_ids = [str(t) for t in (detection.get("tactic_ids") or []) if t]
        technique_ids = [str(t) for t in (detection.get("technique_ids") or []) if t]
        if not tactic_ids and not technique_ids:
            return None
        threat: dict[str, Any] = {"framework": "MITRE ATT&CK"}
        if tactic_ids:
            threat["tactic"] = {"id": tactic_ids}
        if technique_ids:
            threat["technique"] = {"id": technique_ids}
        return threat

    mitre = tool.get("mitre") or {}
    if not mitre:
        return None
    threat = {"framework": "MITRE ATT&CK"}
    tactic = {
        key: mitre[src]
        for key, src in (("id", "tactic_id"), ("name", "tactic"))
        if mitre.get(src)
    }
    technique = {
        key: mitre[src]
        for key, src in (("id", "technique_id"), ("name", "technique"))
        if mitre.get(src)
    }
    if tactic:
        threat["tactic"] = tactic
    if technique:
        threat["technique"] = technique
    # framework alone says nothing. Drop the block rather than ship a label with
    # no technique under it.
    return threat if len(threat) > 1 else None


def canonical_to_ecs(canonical: dict[str, Any]) -> dict[str, Any]:
    """Best-effort ECS 8.x field mapping; full canonical nested under agentmetry."""
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
            "type": "agentmetry",
            "vendor": "agentmetry",
            "product": "Agentmetry",
        },
        "agent": {
            "name": agent.get("name"),
            "version": canonical.get("schema_version"),
        },
        "agentmetry": canonical,
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

    threat = _threat(canonical, tool, action_type)
    if threat is not None:
        doc["threat"] = threat

    if outcome == "denied":
        doc["event"]["type"] = ["denied"]

    fleet_id = str(canonical.get("fleet_id") or "").strip()
    if fleet_id:
        doc["organization"] = {"id": fleet_id}

    return doc
