"""Map Agentmetry canonical events to CloudEvents v1.0 JSON envelopes.

CloudEvents is a CNCF spec for describing an event's *envelope* -- who emitted
it, what kind it is, when -- while leaving the payload alone. That is a good
fit here: the canonical event is already the thing worth keeping, and this adds
a routing header rather than a second schema to maintain.

Why bother when ECS and HEC adapters already exist. Those two speak to one
product each. CloudEvents is what a broker speaks: Knative, EventBridge, Azure
Event Grid, Dapr, NATS and Kafka bindings all consume it, so one adapter
reaches every consumer that is not a SIEM. It is also what Microsoft's Agent
Governance Toolkit emits, which makes a shared bus between the two possible
without either side writing a translator.

Two decisions worth stating.

**The canonical event travels whole, in `data`.** Flattening it into CloudEvents
attributes would mean maintaining a second field list that drifts, and it would
lose the parts that make the record worth having: the hash chain fields, the
MITRE tagging, the traits. Extension attributes carry only what a *router*
needs to make a decision without opening the payload.

**Extension attribute names are lowercase alphanumeric.** CloudEvents 1.0 §3.1
restricts them to `[a-z0-9]`, so no underscores and no dots. `agentmetryseq`
looks wrong and is correct; a consumer that rejects `agentmetry_seq` is right
to. This is the kind of rule that is easy to miss by copying an example, and
the reference implementation this was cross-checked against gets it right too
(`agentmeshentryhash`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

CE_SPECVERSION = "1.0"

#: Reverse-DNS event types, per CloudEvents §3.1.1. Stable strings: a consumer
#: filters on these, so renaming one is a breaking change for a subscriber the
#: same way renaming a trait is for a stored event.
_TYPE_PREFIX = "ai.agentmetry"

_TYPE_MAP = {
    "tool_called": f"{_TYPE_PREFIX}.tool.called",
    "tool_denied": f"{_TYPE_PREFIX}.tool.denied",
    "tool_failed": f"{_TYPE_PREFIX}.tool.failed",
    "detection": f"{_TYPE_PREFIX}.detection.raised",
    "detection_disposition": f"{_TYPE_PREFIX}.detection.dispositioned",
    "approval_request": f"{_TYPE_PREFIX}.approval.requested",
    "approval_response": f"{_TYPE_PREFIX}.approval.responded",
    "session_start": f"{_TYPE_PREFIX}.session.started",
    "session_end": f"{_TYPE_PREFIX}.session.ended",
    "config_change": f"{_TYPE_PREFIX}.config.changed",
    "heartbeat": f"{_TYPE_PREFIX}.heartbeat",
    "mcp_schema": f"{_TYPE_PREFIX}.mcp.schema",
}


def cloudevent_type(action_type: str) -> str:
    """Reverse-DNS type for an action, falling back rather than dropping.

    An unmapped action still gets a well-formed type. Returning None or raising
    would mean a new event type silently stops being forwarded, which is the
    failure mode this project keeps finding in its own code.
    """
    action_type = (action_type or "unknown").strip() or "unknown"
    return _TYPE_MAP.get(action_type, f"{_TYPE_PREFIX}.{action_type.replace('_', '.')}")


def _rfc3339(ts: str) -> str:
    """CloudEvents `time` must be RFC 3339. Canonical timestamps already are,
    modulo the `+00:00` spelling of UTC, which is legal but reads oddly next to
    every other CloudEvents producer."""
    if not ts:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return ts.replace("+00:00", "Z") if ts.endswith("+00:00") else ts


def _source(canonical: dict[str, Any]) -> str:
    """A URI-reference identifying the producer (CloudEvents §3.1.1).

    Host plus the app being recorded, because "which machine and which agent"
    is the question a subscriber routes on. Falls back to the bare scheme
    rather than an empty string: `source` is REQUIRED and non-empty, and an
    envelope that violates that gets rejected by a strict consumer.
    """
    host = str(canonical.get("host_id") or "").strip() or "unknown-host"
    source = canonical.get("source") or {}
    app = str(source.get("app") or "").strip()
    return f"/agentmetry/{host}/{app}" if app else f"/agentmetry/{host}"


def canonical_to_cloudevent(canonical: dict[str, Any]) -> dict[str, Any]:
    """Wrap one canonical event in a CloudEvents v1.0 structured JSON envelope."""
    action = canonical.get("action") or {}
    tool = canonical.get("tool") or {}
    detection = canonical.get("detection") or {}

    action_type = str(action.get("type") or "")

    envelope: dict[str, Any] = {
        "specversion": CE_SPECVERSION,
        "id": str(canonical.get("event_id") or ""),
        "source": _source(canonical),
        "type": cloudevent_type(action_type),
        "time": _rfc3339(str(canonical.get("timestamp_utc") or "")),
        "datacontenttype": "application/json",
        "dataschema": f"https://agentmetry.ai/schemas/event/{canonical.get('schema_version') or '1.1.0'}",
        # The canonical record, unflattened. It is the artifact worth keeping.
        "data": canonical,
    }

    # `subject` is what the event is *about*, and it is what a human reads in a
    # broker console. A detection is about its rule; a tool call is about its
    # tool. Omitted rather than blank when neither applies: CloudEvents forbids
    # empty-string attributes.
    subject = str(detection.get("rule_id") or tool.get("qualified") or tool.get("name") or "")
    if subject:
        envelope["subject"] = subject

    # Extension attributes: only what a router needs in order to filter without
    # parsing `data`.
    #
    # Names are lowercase alphanumeric and at most 20 characters, both from the
    # CloudEvents 1.0 attribute-naming rules. The length limit is a SHOULD and
    # easy to miss, since it appears in the spec prose and in none of the
    # examples: the obvious `agentmetrycorrelationid` is 23 and had to be cut to
    # `agentmetrycorrid`. Some brokers enforce it, and a rejected envelope is a
    # dropped event.
    extensions = {
        "agentmetrycorrid": canonical.get("correlation_id"),
        "agentmetrysession": canonical.get("session_id"),
        "agentmetryfleet": canonical.get("fleet_id"),
        "agentmetryoutcome": action.get("outcome"),
        "agentmetryseverity": detection.get("severity"),
        "agentmetryrule": detection.get("rule_id"),
    }
    for key, value in extensions.items():
        text = str(value or "").strip()
        if text:
            envelope[key] = text

    return envelope


def canonical_to_cloudevents(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [canonical_to_cloudevent(event) for event in events]


#: CloudEvents §3.1: extension attribute names are lowercase alphanumeric.
#: Exposed so a test can assert it over the envelopes rather than restating it.
_RESERVED = frozenset(
    {
        "specversion", "id", "source", "type", "time",
        "datacontenttype", "dataschema", "subject", "data",
    }
)


def extension_attributes(envelope: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in envelope.items() if k not in _RESERVED}
