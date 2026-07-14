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
        "shell": _EXECUTION,
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

_PRIVATE_KEY_PATTERNS = (
    "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa", ".pem", "-----begin", ".ssh/",
)
_CREDENTIAL_PATTERNS = (
    ".aws/credentials", ".aws\\credentials", ".env", ".netrc", ".npmrc",
    ".kube/config", ".kube\\config", "credentials.json", "service-account",
    "secrets.yaml", "secrets.yml",
)


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
        if any(p in text for p in _PRIVATE_KEY_PATTERNS):
            return _PRIVATE_KEY
        if any(p in text for p in _CREDENTIAL_PATTERNS):
            return _CREDENTIAL_ACCESS

    # 2. Tool-name mapping on the method segment (the part after the last '.'),
    #    normalized so Cursor/Claude/driver spellings all land on one entry.
    if not tool_qualified:
        return None
    method = _norm(tool_qualified.rsplit(".", 1)[-1])
    return _TOOL_MAP.get(method)


# Backwards-compatible alias for any callers importing the old name.
MITRE_MAPPINGS = _TOOL_MAP
