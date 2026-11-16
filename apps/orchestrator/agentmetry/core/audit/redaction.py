"""Secret scrubbing for captured command text (Tier A/B).

When command logging is enabled, the raw command string can contain inline
secrets (bearer tokens, basic-auth URLs, --password values, cloud keys) that
key-based argument redaction never sees. Scrub those before storage.

Keep the pattern list in sync with the inline mirror in
`agentmetry/hooks/ingest.py` (the standalone hook cannot import this module);
`tests/test_redaction.py` fails if the two lists differ.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(authorization:\s*)\S+"), r"\1<redacted>"),
    # user:pass@host in URLs
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1<redacted>@"),
    # --password X / --token=X / -p X
    (re.compile(r"(?i)(-{1,2}(?:password|token|secret|api[-_]?key|pwd)[=\s]+)\S+"), r"\1<redacted>"),
    # key=value / key: value assignments. The name may carry a prefix, as in
    # HF_TOKEN=, AWS_SECRET_ACCESS_KEY= or ?access_token=: a `\b` right before
    # the keyword never matched there, because `_` is a word character, so
    # those values were stored as typed. A quoted value is covered too.
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_]*(?:password|passwd|pwd|token|secret|api[-_]?key|apikey"
            r"|access[-_]?key|secret[-_]?key|private[-_]?key))\s*[=:]\s*[\"']?[^\s;&|\"']+"
        ),
        r"\1=<redacted>",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted-aws-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<redacted-key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<redacted-gh-token>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "<redacted-slack-token>"),
    (re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"), "<redacted-hf-token>"),
    # The provider formats the detection rules recognise (traits._ISSUERS),
    # so a token the sensor can name is a token it does not store. Until
    # 0.12.2 `sk-[A-Za-z0-9]{20,}` stopped at the second hyphen, which left
    # OpenAI project keys (`sk-proj-`) and Anthropic keys (`sk-ant-`) stored
    # as typed, along with every format below.
    (re.compile(r"\bsk-(?:ant|proj|svcacct|admin)-[A-Za-z0-9_-]{20,}"), "<redacted-key>"),
    (re.compile(r"\b(?:A3T[A-Z0-9]|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b"), "<redacted-aws-key>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}"), "<redacted-gh-token>"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"), "<redacted-gitlab-token>"),
    (re.compile(r"\bnpm_[A-Za-z0-9]{36,}"), "<redacted-npm-token>"),
    (re.compile(r"\bpypi-[A-Za-z0-9_-]{50,}"), "<redacted-pypi-token>"),
    (re.compile(r"\bdckr_pat_[A-Za-z0-9_-]{20,}"), "<redacted-docker-token>"),
    (re.compile(r"\bAIza[\w-]{35}"), "<redacted-google-key>"),
    (re.compile(r"\bxapp-\d-[A-Za-z0-9]+-\d+-[A-Za-z0-9]+"), "<redacted-slack-token>"),
    (re.compile(r"\b(?:sk|rk)_(?:test|live|prod)_[A-Za-z0-9]{10,99}"), "<redacted-stripe-key>"),
    (re.compile(r"\bSG\.[A-Za-z0-9=_.-]{66}"), "<redacted-sendgrid-key>"),
    (re.compile(r"\bshpat_[a-fA-F0-9]{32}"), "<redacted-shopify-token>"),
    (re.compile(r"\bdo[po]_v1_[a-f0-9]{64}"), "<redacted-digitalocean-token>"),
    (re.compile(r"\blin_api_[A-Za-z0-9]{40}"), "<redacted-linear-key>"),
    (re.compile(r"\bdp\.pt\.[A-Za-z0-9]{43}"), "<redacted-doppler-token>"),
    (re.compile(r"\bPMAK-[a-fA-F0-9]{24}-[a-fA-F0-9]{34}"), "<redacted-postman-key>"),
    (re.compile(r"\bpul-[a-f0-9]{40}"), "<redacted-pulumi-token>"),
    (re.compile(r"\bdapi[a-f0-9]{32}(?:-\d)?"), "<redacted-databricks-token>"),
]


def scrub_secrets(text: str) -> str:
    """Mask obvious inline secrets in a command/string. Best-effort, conservative."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


#: Argument keys whose value is never stored, at any depth. Mirrors the hook's
#: REDACT_KEYS (see test). Applied here as well because not every client is
#: the hook: an SDK adapter posting `{"password": ...}` used to be kept as sent.
REDACT_KEYS = frozenset({
    "token", "api_key", "apikey", "password", "secret", "authorization",
    "anthropic_api_key", "openai_api_key",
})

#: Mirrors the hook's SCRUB_MAX_DEPTH.
SCRUB_MAX_DEPTH = 32


def scrub_arg_values(args: object, _depth: int = 0) -> object:
    """Mask secrets in stored arguments at every depth, not only the top.

    Sensitive keys are redacted wherever they sit and every string is scrubbed,
    lists included. Until 0.10.5 only top-level string values were scrubbed, so
    a nested token in full-argument capture was stored as sent. Best effort:
    the patterns catch shapes, not every secret.
    """
    if _depth > SCRUB_MAX_DEPTH:
        return "<redacted-depth>"
    if isinstance(args, dict):
        return {
            k: "<redacted>" if str(k).lower() in REDACT_KEYS else scrub_arg_values(v, _depth + 1)
            for k, v in args.items()
        }
    if isinstance(args, (list, tuple)):
        return [scrub_arg_values(v, _depth + 1) for v in args]
    return scrub_secrets(args) if isinstance(args, str) else args
