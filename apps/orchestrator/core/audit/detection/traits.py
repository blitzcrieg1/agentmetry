"""Command classification shared by the sequence rules and the hook client.

The default privacy configuration hashes tool arguments inside the hook process
and never stores command text, which left every command-regex rule blind on real
captured traffic: the demo and the tests injected `command`, production events
did not have one. The fix is to classify the command *where the plaintext is
still visible* — in the hook, before hashing — and ship only category labels
(`tool.traits`). No command text leaves the machine; the rules match the labels
when the text is absent.

This module is imported by scripts/agentmetry_ingest.py via the same sys.path
mechanism as the DLP scanner, so it must stay dependency-free: `re` only, no
core.config, no pydantic.

Rule docstrings explaining each pattern's provenance stay in rules.py; this
module owns the regexes so the hook and the rules cannot drift apart.
"""

from __future__ import annotations

import re

# A raw-IP URL and a download/execute verb in the same command is a classic
# malware download cradle. Legit tooling uses domains and package managers.
RAW_IP_URL = re.compile(r"https?://((?:\d{1,3}\.){3}\d{1,3})")
# Loopback is not ingress — fetching your own orchestrator's health endpoint
# must not read as a download cradle (see rules.py for the war story).
LOOPBACK_IP = re.compile(r"^(?:127(?:\.\d{1,3}){3}|0\.0\.0\.0)$")
DOWNLOAD_EXEC = re.compile(
    r"downloadstring|downloadfile|invoke-webrequest|\biwr\b|\bcurl\b|\bwget\b|"
    r"certutil|bitsadmin|invoke-expression|\biex\b",
    re.IGNORECASE,
)
ENCODED_CMD = re.compile(r"-enc(odedcommand)?\b|frombase64string", re.IGNORECASE)

# Fetch remote content and feed it straight to an interpreter (ADI §4.2).
PIPE_TO_SHELL = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*[|]\s*"
    r"(sudo\s+)?\b(ba|z|k|da)?sh\b|"
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*[|]\s*"
    r"(iex|invoke-expression|python\d?|perl|ruby|node)\b",
    re.IGNORECASE,
)

# `bash: rm -rf build/` is a deletion even though the tool is named "Bash".
DELETE_COMMAND = re.compile(
    r"\brm\s+(-[a-z]*\s+)*|\brmdir\b|\bunlink\b|remove-item\b|\bdel\s+/", re.IGNORECASE
)

# Content an outsider can author (gh issues/PRs, git fetch) — ADI provenance.
UNTRUSTED_INPUT_COMMAND = re.compile(
    r"\bgh\s+(issue|pr)\s+(view|list|diff|comment)|"
    r"\bgit\s+(fetch|pull|clone)\b",
    re.IGNORECASE,
)

# PR review provenance (ADI §4.3): description vs code vs merge.
PR_DESC_COMMAND = re.compile(r"\bgh\s+pr\s+view\b", re.IGNORECASE)
PR_COMMIT_COMMAND = re.compile(
    r"\bgh\s+pr\s+(diff|checkout|files)\b|\bgit\s+show\b", re.IGNORECASE
)
PR_MERGE_COMMAND = re.compile(r"\bgh\s+pr\s+merge\b|\bgit\s+merge\b", re.IGNORECASE)

# Cloud and cluster APIs used after credential harvest (HF July 2026 lateral phase).
CLOUD_API = re.compile(
    r"\bkubectl\b|"
    r"(?:^|\s)aws\s+\w|"
    r"\bgcloud\b|"
    r"\baz\s+(?:account|login|keyvault|aks|storage)\b|"
    r"\b(?:hf|huggingface-cli)\b|"
    r"\baliyun\b|\btencentcloud\b|\bbce\b|\bossutil\b|\bcoscmd\b",
    re.IGNORECASE,
)

# Push harvested material to a remote the operator did not intend (Nx s1ngularity).
GIT_EXFIL = re.compile(
    r"\bgit\s+push\b|"
    r"\bgh\s+repo\s+(?:create|sync)\b|"
    r"\bgh\s+release\s+upload\b",
    re.IGNORECASE,
)

# Public staging hosts used for agent C2 (gist, HF raw files, GitHub raw content).
STAGING_HOST = re.compile(
    r"https?://(?:[\w-]+\.)?(?:"
    r"githubusercontent\.com|gist\.github\.com|raw\.github\.com|"
    r"huggingface\.co|pastebin\.com|gitlab\.com|bitbucket\.org"
    r")",
    re.IGNORECASE,
)
STAGING_FETCH = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b",
    re.IGNORECASE,
)
# Second-step execution after a staged download — excludes package managers.
RISKY_EXEC_AFTER_STAGING = re.compile(
    r"\b(bash|sh|zsh|dash)\s+[\w./~-]+\.(?:sh|bash)\b|"
    r"\bpython\d?\s+[\w./~-]+\.py\b|"
    r"\bpython\d?\s+-c\b|"
    r"\b(iex|invoke-expression|eval)\b|"
    r"\bpowershell(?:\.exe)?\s+-(?:enc|f|file)\b",
    re.IGNORECASE,
)
BENIGN_AFTER_STAGING = re.compile(
    r"\b(npm|yarn|pnpm|pip|pip3|cargo|go)\s+(?:install|run|build)\b",
    re.IGNORECASE,
)

# Stable vocabulary. Renaming a trait is a breaking change for stored events:
# rules match these strings on events that may be replayed months later.
KNOWN_TRAITS = frozenset({
    "raw_ip_fetch",
    "encoded_cmd",
    "pipe_to_shell",
    "cloud_api",
    "git_exfil",
    "staging_fetch",
    "risky_exec",
    "delete_cmd",
    "untrusted_input",
    "pr_desc",
    "pr_commit",
    "pr_merge",
})


def classify_command(command: str) -> list[str]:
    """Map a plaintext command to detection trait labels (never the text itself)."""
    if not command or not isinstance(command, str):
        return []
    traits: list[str] = []

    remote_ips = [ip for ip in RAW_IP_URL.findall(command) if not LOOPBACK_IP.match(ip)]
    if remote_ips and DOWNLOAD_EXEC.search(command):
        traits.append("raw_ip_fetch")
    if ENCODED_CMD.search(command):
        traits.append("encoded_cmd")
    if PIPE_TO_SHELL.search(command):
        traits.append("pipe_to_shell")
    if CLOUD_API.search(command):
        traits.append("cloud_api")
    if GIT_EXFIL.search(command):
        traits.append("git_exfil")
    if STAGING_HOST.search(command) and (
        STAGING_FETCH.search(command) or DOWNLOAD_EXEC.search(command)
    ):
        traits.append("staging_fetch")
    if not BENIGN_AFTER_STAGING.search(command) and (
        PIPE_TO_SHELL.search(command) or RISKY_EXEC_AFTER_STAGING.search(command)
    ):
        traits.append("risky_exec")
    if DELETE_COMMAND.search(command):
        traits.append("delete_cmd")
    if UNTRUSTED_INPUT_COMMAND.search(command):
        traits.append("untrusted_input")
    if PR_DESC_COMMAND.search(command):
        traits.append("pr_desc")
    if PR_COMMIT_COMMAND.search(command):
        traits.append("pr_commit")
    if PR_MERGE_COMMAND.search(command):
        traits.append("pr_merge")
    return traits
