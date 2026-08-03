"""Secret scrubbing for captured command text (Tier A/B).

When command logging is enabled, the raw command string can contain inline
secrets (bearer tokens, basic-auth URLs, --password values, cloud keys) that
key-based argument redaction never sees. Scrub those before storage.

Keep the pattern list in sync with the inline mirror in
`scripts/agentmetry_ingest.py` (the standalone hook cannot import this module).
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
    # key=value / key: value assignments
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|token|secret|api[-_]?key|apikey|access[-_]?key)\s*[=:]\s*[^\s;&|\"']+"
        ),
        r"\1=<redacted>",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted-aws-key>"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "<redacted-key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "<redacted-gh-token>"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "<redacted-slack-token>"),
]


def scrub_secrets(text: str) -> str:
    """Mask obvious inline secrets in a command/string. Best-effort, conservative."""
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def scrub_arg_values(args: object) -> object:
    """Scrub secret patterns inside string values of an arguments dict."""
    if not isinstance(args, dict):
        return args
    return {k: (scrub_secrets(v) if isinstance(v, str) else v) for k, v in args.items()}
