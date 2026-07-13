"""Behavioral sequence rules.

Per-event MITRE tagging (core/audit/mitre.py) says *what* a single tool call is.
These rules say what a *sequence* of calls means — the signal an EDR/CASB can't
see because it never had the agent's intent or the session boundary.

Each rule is a pure function: ``list[event] (time-ordered) -> list[Detection]``.
Add a rule by writing a function and appending it to REGISTRY.
"""

from __future__ import annotations

from typing import Any

from .models import Detection

# --- safe accessors ----------------------------------------------------------
# Events are plain dicts read from JSONL; never assume a nested key exists.


def _mitre(event: dict[str, Any]) -> dict[str, Any]:
    tool = event.get("tool")
    if isinstance(tool, dict):
        mitre = tool.get("mitre")
        if isinstance(mitre, dict):
            return mitre
    return {}


def _tactic_id(event: dict[str, Any]) -> str:
    return str(_mitre(event).get("tactic_id") or "")


def _technique_id(event: dict[str, Any]) -> str:
    return str(_mitre(event).get("technique_id") or "")


def _actor_type(event: dict[str, Any]) -> str:
    initiator = event.get("initiator")
    return str(initiator.get("actor_type") or "") if isinstance(initiator, dict) else ""


def _action(event: dict[str, Any]) -> dict[str, Any]:
    action = event.get("action")
    return action if isinstance(action, dict) else {}


def _action_type(event: dict[str, Any]) -> str:
    return str(_action(event).get("type") or "")


def _outcome(event: dict[str, Any]) -> str:
    return str(_action(event).get("outcome") or "")


def _tool_qualified(event: dict[str, Any]) -> str:
    tool = event.get("tool")
    return str(tool.get("qualified") or "") if isinstance(tool, dict) else ""


def _event_id(event: dict[str, Any]) -> str:
    return str(event.get("event_id") or "")


def _ts(event: dict[str, Any]) -> str:
    return str(event.get("timestamp_utc") or "")


def _correlation_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        cid = event.get("correlation_id")
        if cid:
            return str(cid)
    return ""


# --- rules -------------------------------------------------------------------

_DISCOVERY_BURST = 3  # list_dir/glob calls that read as recon before a grab


def rule_credential_exfil(events: list[dict[str, Any]]) -> list[Detection]:
    """Credential access (T1552) then network egress (TA0011) in one session.

    The read-a-secret-then-phone-home pattern. Critical: this is exfiltration of
    exactly the data a SOC cares about, and no single event looks like an alert.
    """
    cred_idx = next(
        (i for i, e in enumerate(events) if _technique_id(e).startswith("T1552")),
        None,
    )
    if cred_idx is None:
        return []

    for net in events[cred_idx + 1:]:
        if _tactic_id(net) == "TA0011":
            cred = events[cred_idx]
            return [
                Detection(
                    rule_id="credential-exfil",
                    title="Credential access followed by network egress",
                    severity="critical",
                    summary=(
                        f"{_tool_qualified(cred) or 'a tool'} accessed credentials, then "
                        f"{_tool_qualified(net) or 'a tool'} egressed to the network in the "
                        "same session."
                    ),
                    correlation_id=_correlation_id(events),
                    tactic_ids=["TA0006", "TA0011"],
                    technique_ids=[_technique_id(cred), _technique_id(net)],
                    event_ids=[_event_id(cred), _event_id(net)],
                    first_seen_utc=_ts(cred),
                    last_seen_utc=_ts(net),
                )
            ]
    return []


def rule_autonomous_unapproved_write(events: list[dict[str, Any]]) -> list[Detection]:
    """Autonomous agent performs an Impact action with no human approval first.

    The flagship "no default self-approve" story: an agent running on its own
    (cron/vault_watch/ingress) wrote, edited, or deleted before any human
    approval_response landed in the session. A granted approval resets the gate.
    """
    offending: list[dict[str, Any]] = []
    approved = False
    for event in events:
        if _action_type(event) == "approval_response" and _outcome(event) == "success":
            approved = True
            continue
        if (
            not approved
            and _action_type(event) == "tool_called"
            and _outcome(event) == "success"
            and _tactic_id(event) == "TA0040"
            and _actor_type(event) == "autonomous"
        ):
            offending.append(event)

    if not offending:
        return []

    return [
        Detection(
            rule_id="autonomous-unapproved-write",
            title="Autonomous write without human approval",
            severity="high",
            summary=(
                f"{len(offending)} impact action(s) (write/edit/delete) by an autonomous "
                "agent with no human approval in the session."
            ),
            correlation_id=_correlation_id(events),
            tactic_ids=["TA0040"],
            technique_ids=sorted({_technique_id(e) for e in offending if _technique_id(e)}),
            event_ids=[_event_id(e) for e in offending],
            first_seen_utc=_ts(offending[0]),
            last_seen_utc=_ts(offending[-1]),
        )
    ]


def rule_discovery_then_collect(events: list[dict[str, Any]]) -> list[Detection]:
    """A burst of Discovery (TA0007) then Collection/Credential-Access — recon.

    Enumerating the filesystem and then reading files is the classic recon-then-
    grab shape. Medium: benign on its own, meaningful as a lead-in.
    """
    burst: list[dict[str, Any]] = []
    for event in events:
        tactic = _tactic_id(event)
        if tactic == "TA0007":
            burst.append(event)
        elif tactic in ("TA0009", "TA0006") and len(burst) >= _DISCOVERY_BURST:
            collect = event
            technique_ids = sorted({_technique_id(e) for e in burst if _technique_id(e)})
            if _technique_id(collect):
                technique_ids.append(_technique_id(collect))
            return [
                Detection(
                    rule_id="discovery-then-collect",
                    title="Filesystem recon followed by data collection",
                    severity="medium",
                    summary=(
                        f"{len(burst)} discovery calls preceded {_tool_qualified(collect) or 'a read'} "
                        "collecting data in the same session."
                    ),
                    correlation_id=_correlation_id(events),
                    tactic_ids=["TA0007", tactic],
                    technique_ids=technique_ids,
                    event_ids=[_event_id(e) for e in burst] + [_event_id(collect)],
                    first_seen_utc=_ts(burst[0]),
                    last_seen_utc=_ts(collect),
                )
            ]
    return []


def rule_approval_denied_then_executed(events: list[dict[str, Any]]) -> list[Detection]:
    """A human denied a gated action, and the exact same action executed successfully later.
    
    Binds the denial event to the subsequent execution event by matching the qualified tool name
    (either tool.qualified or gated_action.tool on the denial, matching tool.qualified on the execution).
    """
    denied_tools: dict[str, dict[str, Any]] = {}
    detections: list[Detection] = []
    
    for event in events:
        action_type = _action_type(event)
        outcome = _outcome(event)
        
        if action_type == "approval_response" and outcome == "denied":
            tool_name = _tool_qualified(event)
            if not tool_name:
                gated = event.get("gated_action")
                if isinstance(gated, dict):
                    tool_name = str(gated.get("tool") or "")
            if tool_name:
                denied_tools[tool_name] = event
                
        elif action_type == "tool_called" and outcome == "success":
            tool_name = _tool_qualified(event)
            if tool_name and tool_name in denied_tools:
                denial = denied_tools[tool_name]
                detections.append(
                    Detection(
                        rule_id="approval-denied-then-executed",
                        title="Denied action was executed",
                        severity="critical",
                        summary=(
                            f"Tool '{tool_name}' was successfully executed after being explicitly "
                            "denied earlier in the session."
                        ),
                        correlation_id=_correlation_id(events),
                        tactic_ids=["TA0005"],
                        technique_ids=[],
                        event_ids=[_event_id(denial), _event_id(event)],
                        first_seen_utc=_ts(denial),
                        last_seen_utc=_ts(event),
                    )
                )
                del denied_tools[tool_name]
                
    return detections


REGISTRY = [
    rule_credential_exfil,
    rule_autonomous_unapproved_write,
    rule_discovery_then_collect,
    rule_approval_denied_then_executed,
]
