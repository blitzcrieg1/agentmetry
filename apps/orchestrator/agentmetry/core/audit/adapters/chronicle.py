"""Google SecOps (Chronicle) UDM envelope for Agentmetry canonical events.

Chronicle normalises everything it stores into the Unified Data Model, and there
are two ways to get there. You can post raw JSON to `unstructuredlogentries` and
have a Config Based Normalization parser turn it into UDM, or you can post UDM
directly to `udmevents` and skip the parser entirely.

This emits UDM directly, and the reason is maintenance rather than performance.
A CBN parser is a second implementation of this mapping, written in a different
language, living in the customer's tenant, versioned separately, and updated by
somebody who is not us. Every schema change would then need to land twice and
stay in step, and the failure mode when they drift is silent: events keep
arriving and quietly stop populating the fields the detections key on. Google's
own guidance is to send UDM where you can, for the same reason.

## The part that breaks ingestion if you get it wrong

`metadata.event_type` is not a label. It determines which UDM fields Chronicle
*requires*, so a mis-declared type is rejected at ingest rather than stored
imperfectly. PROCESS_LAUNCH without a process, NETWORK_HTTP without network
fields: both fail. That is why the mapping below is conservative. Where the
canonical event does not clearly carry what a specific type demands, it falls
back to USER_RESOURCE_ACCESS, which needs only a principal and a target and is
honest about what an agent tool call actually is.

The temptation is to map aggressively for prettier dashboards. A tool call that
reads a file is *not* the same evidence as an EDR-observed FILE_READ, because
Agentmetry sees the agent's intent to read rather than the kernel's record of a
read. Claiming the stronger type would make the two indistinguishable in a
Chronicle search, which is exactly the confusion a SOC does not need.

## What a detection becomes

A detection maps to USER_RESOURCE_ACCESS carrying a populated `security_result`
with `alert_state: ALERTING`. Chronicle's own alerting keys on security_result,
so a customer writes YARA-L against `security_result.severity` and
`security_result.rule_name` without learning Agentmetry's vocabulary.

## What a heartbeat becomes

STATUS_UPDATE, which is the type Chronicle documents for endpoint status and
configuration reporting. That is precisely what the heartbeat is, and it means
the "recorder went silent" rule is an absence check over a native UDM type
rather than over a vendor-specific event.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VENDOR = "Agentmetry"
PRODUCT = "Agentmetry"

#: Chronicle severity vocabulary. Anything unrecognised becomes INFORMATIONAL
#: rather than being dropped: an unmapped severity should still be searchable.
_SEVERITY = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "info": "INFORMATIONAL",
    "informational": "INFORMATIONAL",
}

#: Tool method fragments that genuinely describe a process launch. Kept narrow on
#: purpose: PROCESS_LAUNCH requires a process in the UDM record, and a mis-typed
#: event is rejected at ingest rather than stored badly.
_EXEC_HINTS = ("bash", "shell", "powershell", "run", "exec", "terminal", "cmd")


def _rfc3339(ts: str) -> str:
    """Chronicle wants RFC 3339 with a Z suffix."""
    if not ts:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _method(canonical: dict[str, Any]) -> str:
    tool = canonical.get("tool") or {}
    qualified = str(tool.get("qualified") or tool.get("name") or "")
    return qualified.rsplit(".", 1)[-1].lower()


def udm_event_type(canonical: dict[str, Any]) -> str:
    """Pick the narrowest UDM type the event actually supports.

    Deliberately conservative. Chronicle validates required fields per type, so
    over-claiming fails ingestion, and it would also overstate the evidence: a
    recorded intent to read a file is not a kernel-observed FILE_READ.
    """
    action_type = str((canonical.get("action") or {}).get("type") or "")

    if action_type == "heartbeat":
        return "STATUS_UPDATE"
    if action_type in ("session_start", "session_end"):
        return "USER_RESOURCE_ACCESS"
    if action_type == "config_change":
        return "STATUS_UPDATE"
    if action_type in ("tool_called", "tool_denied", "tool_failed"):
        tool = canonical.get("tool") or {}
        if any(hint in _method(canonical) for hint in _EXEC_HINTS) and tool.get("command"):
            return "PROCESS_LAUNCH"
        return "USER_RESOURCE_ACCESS"
    return "USER_RESOURCE_ACCESS"


def _security_result(canonical: dict[str, Any]) -> dict[str, Any] | None:
    """The verdict, in the shape Chronicle's alerting already understands.

    A customer should be able to write YARA-L against `security_result.severity`
    without learning what a `detection.rule_id` is. Vocabulary a SIEM has to be
    taught is vocabulary nobody writes rules against.
    """
    action = canonical.get("action") or {}
    action_type = str(action.get("type") or "")
    outcome = str(action.get("outcome") or "").lower()

    if action_type == "detection":
        detection = canonical.get("detection") or {}
        result: dict[str, Any] = {
            "alert_state": "ALERTING",
            "severity": _SEVERITY.get(str(detection.get("severity") or outcome), "INFORMATIONAL"),
            "rule_name": str(detection.get("title") or detection.get("rule_id") or ""),
            "rule_id": str(detection.get("rule_id") or ""),
            "summary": str(detection.get("summary") or action.get("reason") or ""),
            "category_details": [str(t) for t in (detection.get("technique_ids") or [])],
        }
        return {k: v for k, v in result.items() if v not in ("", [], None)}

    if action_type == "tool_denied":
        return {
            "action": ["BLOCK"],
            "severity": "MEDIUM",
            "summary": str(action.get("reason") or "tool call denied by policy"),
        }

    if action_type == "heartbeat" and outcome == "degraded":
        return {
            "alert_state": "ALERTING",
            "severity": "MEDIUM",
            "rule_name": "Agentmetry recorder degraded",
            "rule_id": "agentmetry-recorder-degraded",
            "summary": str(action.get("reason") or "recorder attesting degraded"),
        }

    if outcome in ("success", ""):
        return {"action": ["ALLOW"]} if action_type.startswith("tool_") else None
    return None


def _principal(canonical: dict[str, Any]) -> dict[str, Any]:
    """Who acted. The host and the operator, plus the agent as the process."""
    actor = canonical.get("actor") or {}
    initiator = canonical.get("initiator") or {}
    agent = canonical.get("agent") or {}

    principal: dict[str, Any] = {}
    if canonical.get("host_id"):
        principal["hostname"] = str(canonical["host_id"])
    userid = str(actor.get("id") or initiator.get("operator_id") or "")
    if userid:
        principal["user"] = {"userid": userid}
    if agent.get("name"):
        # The agent is the thing that acted, so it belongs in principal.process
        # rather than in a label. That is what makes a Chronicle pivot from a
        # finding to "everything this agent did" work at all.
        principal["application"] = str(agent["name"])
    return principal


def _target(canonical: dict[str, Any]) -> dict[str, Any]:
    """What was acted on: the tool, and its command when one was captured."""
    tool = canonical.get("tool") or {}
    target: dict[str, Any] = {}

    qualified = str(tool.get("qualified") or tool.get("name") or "")
    if qualified:
        target["application"] = qualified

    command = str(tool.get("command") or "")
    if command:
        # Truncated because a UDM string field is not a log body and a 100 KB
        # heredoc in a search result helps nobody.
        target["process"] = {"command_line": command[:4000]}

    if canonical.get("fleet_id"):
        target["administrative_domain"] = str(canonical["fleet_id"])

    # USER_RESOURCE_ACCESS and PROCESS_LAUNCH both require a target, and a
    # detection carries no tool: it is a finding about a session rather than
    # about one call. An empty target here is not a cosmetic gap, it is an
    # ingest rejection, and the event is then missing from the SIEM entirely
    # while everything upstream reports success.
    if not target:
        session = str(canonical.get("correlation_id") or canonical.get("session_id") or "")
        target["resource"] = {
            "resource_type": "VIRTUAL_MACHINE" if not session else "UNSPECIFIED",
            "name": session or f"agentmetry:{canonical.get('host_id') or 'unknown-host'}",
        }
    return target


def canonical_to_udm(canonical: dict[str, Any]) -> dict[str, Any]:
    """One canonical event as a single Chronicle UDM event."""
    action = canonical.get("action") or {}
    event_type = udm_event_type(canonical)

    metadata: dict[str, Any] = {
        "event_timestamp": _rfc3339(str(canonical.get("timestamp_utc") or "")),
        "event_type": event_type,
        "vendor_name": VENDOR,
        "product_name": PRODUCT,
        "product_version": str(canonical.get("schema_version") or ""),
        "product_event_type": str(action.get("type") or ""),
        "product_log_id": str(canonical.get("event_id") or ""),
    }
    description = str(action.get("reason") or "")
    if description:
        metadata["description"] = description[:1000]

    udm: dict[str, Any] = {
        "metadata": {k: v for k, v in metadata.items() if v},
        "principal": _principal(canonical),
        "target": _target(canonical),
    }

    security_result = _security_result(canonical)
    if security_result:
        udm["security_result"] = [security_result]

    # Correlation id is how a responder pivots from one finding to the whole
    # agent session, so it must survive as a first-class searchable value rather
    # than being buried in a JSON blob.
    labels = []
    for key in ("correlation_id", "session_id"):
        value = str(canonical.get(key) or "")
        if value:
            labels.append({"key": key, "value": value})
    source = canonical.get("source") or {}
    if source.get("app"):
        labels.append({"key": "source_app", "value": str(source["app"])})
    if labels:
        udm["additional"] = {"labels": labels}

    return {k: v for k, v in udm.items() if v}


def canonical_to_udm_batch(events: list[dict[str, Any]], *, customer_id: str = "") -> dict[str, Any]:
    """The `udmevents` request body: a list of UDM events under one customer."""
    body: dict[str, Any] = {"events": [canonical_to_udm(e) for e in events]}
    if customer_id:
        body["customer_id"] = customer_id
    return body
