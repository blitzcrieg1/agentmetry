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


# Tool method (segment after the last '.') -> technique.
_TOOL_MAP: dict[str, dict[str, str]] = {
    # Execution
    "run_command": _m("TA0002", "Execution", "T1059", "Command and Scripting Interpreter"),
    "run_terminal_cmd": _m("TA0002", "Execution", "T1059", "Command and Scripting Interpreter"),
    "shell": _m("TA0002", "Execution", "T1059", "Command and Scripting Interpreter"),
    "bash": _m("TA0002", "Execution", "T1059.004", "Unix Shell"),
    "powershell": _m("TA0002", "Execution", "T1059.001", "PowerShell"),
    "exec": _m("TA0002", "Execution", "T1059", "Command and Scripting Interpreter"),
    # Collection
    "read_file": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    "read_note": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    "view_file": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    "read": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    "grep_search": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    "grep": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    "codebase_search": _m("TA0009", "Collection", "T1005", "Data from Local System"),
    # Discovery
    "list_dir": _m("TA0007", "Discovery", "T1083", "File and Directory Discovery"),
    "glob": _m("TA0007", "Discovery", "T1083", "File and Directory Discovery"),
    "ls": _m("TA0007", "Discovery", "T1083", "File and Directory Discovery"),
    # Impact / Manipulation
    "write_file": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "write_to_file": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "write": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "edit_file": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "edit": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "replace_file_content": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "multi_replace_file_content": _m("TA0040", "Impact", "T1565", "Data Manipulation"),
    "delete_file": _m("TA0040", "Impact", "T1485", "Data Destruction"),
    # Command & Control / network
    "curl": _m("TA0011", "Command and Control", "T1071.001", "Web Protocols"),
    "wget": _m("TA0011", "Command and Control", "T1071.001", "Web Protocols"),
    "fetch": _m("TA0011", "Command and Control", "T1071.001", "Web Protocols"),
    "http_request": _m("TA0011", "Command and Control", "T1071.001", "Web Protocols"),
    "web_search": _m("TA0011", "Command and Control", "T1071.001", "Web Protocols"),
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

    # 2. Tool-name mapping: exact qualified name, then the method segment.
    if tool_qualified in _TOOL_MAP:
        return _TOOL_MAP[tool_qualified]
    method = tool_qualified.rsplit(".", 1)[-1].lower() if tool_qualified else ""
    if method in _TOOL_MAP:
        return _TOOL_MAP[method]
    return None


# Backwards-compatible alias for any callers importing the old name.
MITRE_MAPPINGS = _TOOL_MAP
