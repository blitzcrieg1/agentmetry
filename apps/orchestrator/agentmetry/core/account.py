"""Validate and minimise the account identity a coding agent reports.

This module deliberately has no Agentmetry imports. Hook processes import it
before the receiver, and a malformed account claim must never break capture.
The value is a client claim, not proof of identity.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_EMAIL_MAX = 320
_DOMAIN_MAX = 253
_ORG_MAX = 256
_SOURCE_MAX = 32
_TRUE = frozenset({"1", "true", "yes", "on"})
_LOCAL_CONFIG_MAX_BYTES = 1024 * 1024
_ACCOUNT_ID_MAX = 128
_ACCOUNT_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_:."
)
#: The first line of a Codex session file also holds its base instructions.
_SESSION_META_MAX_BYTES = 1024 * 1024
_WINDOWS_EXTENDED_PREFIX = chr(92) * 2 + "?" + chr(92)
_CODEX_AUTH_MAX_BYTES = 256 * 1024
_FALSE = frozenset({"0", "false", "no", "off"})
_CLAUDE_AUTH_OVERRIDE_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_PROFILE",
)
_CLAUDE_PROVIDER_FLAGS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return ""
    return value


def _valid_domain(domain: str) -> bool:
    if not domain or len(domain) > _DOMAIN_MAX or domain.endswith("."):
        return False
    labels = domain.split(".")
    return all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(ch.isalnum() or ch == "-" for ch in label)
        for label in labels
    )


def account_from_email(
    value: Any,
    source: str,
    organization_id: Any = "",
    *,
    include_email: bool | None = None,
) -> dict[str, str]:
    """Return a bounded account block, or an empty block for bad input."""
    raw = _clean_text(value, _EMAIL_MAX)
    if raw.count("@") != 1:
        return {}
    local, domain = raw.rsplit("@", 1)
    if not local or any(ch.isspace() for ch in raw):
        return {}
    domain = domain.lower()
    if not _valid_domain(domain):
        return {}

    source_text = _clean_text(source, _SOURCE_MAX).lower()
    if not source_text:
        source_text = "client"
    org = _clean_text(organization_id, _ORG_MAX)
    block = {"domain": domain, "source": source_text}
    if org:
        block["organization_id"] = org
    if include_email is None:
        include_email = os.environ.get("AGENTMETRY_LOG_ACCOUNT_EMAIL", "").strip().lower() in _TRUE
    if include_email:
        # Keep the local part as reported, but normalise the domain.
        block["email"] = f"{local}@{domain}"
    return block


def account_from_domain(
    domain: Any,
    source: Any,
    organization_id: Any = "",
    email: Any = "",
    *,
    include_email: bool | None = None,
) -> dict[str, str]:
    """Validate an already-minimised claim, optionally retaining opt-in email."""
    clean_domain = _clean_text(domain, _DOMAIN_MAX).lower()
    if not _valid_domain(clean_domain):
        return {}
    source_text = _clean_text(source, _SOURCE_MAX).lower() or "client"
    org = _clean_text(organization_id, _ORG_MAX)
    block = {"domain": clean_domain, "source": source_text}
    if org:
        block["organization_id"] = org
    if include_email is None:
        include_email = os.environ.get("AGENTMETRY_LOG_ACCOUNT_EMAIL", "").strip().lower() in _TRUE
    if include_email:
        candidate = account_from_email(email, source_text, org, include_email=True)
        if candidate and candidate.get("domain") == clean_domain:
            block["email"] = candidate["email"]
    return block


def account_from_organization(organization_id: Any, source: str) -> dict[str, str]:
    """Return an organization-only claim when no email was reported."""
    org = _clean_text(organization_id, _ORG_MAX)
    source_text = _clean_text(source, _SOURCE_MAX).lower() or "client"
    return {"organization_id": org, "source": source_text} if org else {}


def _clean_id(value: Any) -> str:
    text = _clean_text(value, _ACCOUNT_ID_MAX)
    return text if text and all(ch in _ACCOUNT_ID_CHARS for ch in text) else ""


def account_from_ids(account_id: Any, user_id: Any, source: Any) -> dict[str, str]:
    """Return a claim of opaque account IDs. It names no domain and no address."""
    account = _clean_id(account_id)
    user = _clean_id(user_id)
    if not account and not user:
        return {}
    block = {"source": _clean_text(source, _SOURCE_MAX).lower() or "client"}
    if account:
        block["account_id"] = account
    if user:
        block["user_id"] = user
    return block


def account_from_claim(
    domain: Any,
    source: Any,
    organization_id: Any = "",
    email: Any = "",
    *,
    account_id: Any = "",
    user_id: Any = "",
    include_email: bool | None = None,
) -> dict[str, str]:
    """Keep whichever valid parts of a claim arrived: domain, organization or IDs."""
    account = account_from_domain(
        domain, source, organization_id, email, include_email=include_email
    ) or account_from_organization(organization_id, source)
    ids = account_from_ids(account_id, user_id, source)
    return {**ids, **account} if account else ids


def _claude_auth_override_present() -> bool:
    """Return whether visible environment state selects non-subscription auth."""
    if any(os.environ.get(name, "").strip() for name in _CLAUDE_AUTH_OVERRIDE_VARS):
        return True
    if any(os.environ.get(name, "").strip().lower() in _TRUE for name in _CLAUDE_PROVIDER_FLAGS):
        return True
    if os.environ.get("ANTHROPIC_FEDERATION_RULE_ID", "").strip() and os.environ.get(
        "ANTHROPIC_ORGANIZATION_ID", ""
    ).strip():
        return True
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
    if base_url:
        try:
            hostname = urlsplit(base_url).hostname
        except ValueError:
            return True
        if hostname != "api.anthropic.com":
            return True
    return False


def _local_claude_account() -> dict[str, str]:
    """Read two non-secret fields from Claude's undocumented local file.

    The file and its JSON shape can change between Claude Code versions. It is
    bounded and read once per short-lived hook invocation. An oversized file
    is ignored rather than partially parsed. Explicit API credentials or a
    custom endpoint take precedence over the signed-in account, so the local
    fallback is skipped when any documented override is present.
    """
    if _claude_auth_override_present():
        return {}
    try:
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
        path = (Path(config_dir) if config_dir else Path.home()) / ".claude.json"
        if not path.is_file() or path.stat().st_size > _LOCAL_CONFIG_MAX_BYTES:
            return {}
        parsed = json.loads(path.read_bytes())
        oauth = parsed.get("oauthAccount") if isinstance(parsed, dict) else None
        email = oauth.get("emailAddress") if isinstance(oauth, dict) else None
        organization_id = oauth.get("organizationUuid") if isinstance(oauth, dict) else None
        if isinstance(email, str):
            account = account_from_email(email, "local_config", organization_id)
            if account:
                return account
        return account_from_organization(organization_id, "local_config")
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def _antigravity_storage_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "Antigravity" / "app_storage.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Antigravity" / "app_storage.json"
    base = os.environ.get("XDG_CONFIG_HOME", "")
    return (Path(base) if base else Path.home() / ".config") / "Antigravity" / "app_storage.json"


def _local_antigravity_account() -> dict[str, str]:
    """Read the last sign-in name from Antigravity's undocumented app storage.

    Its hook input has no account field. This one key names the account last
    signed in on the machine, not necessarily the one that made the call, and
    the key can change between versions. This file holds no credentials.
    """
    try:
        path = _antigravity_storage_path()
        if not path.is_file() or path.stat().st_size > _LOCAL_CONFIG_MAX_BYTES:
            return {}
        parsed = json.loads(path.read_bytes())
        if not isinstance(parsed, dict):
            return {}
        return account_from_email(parsed.get("jetski.onboarding.lastLoginUsername"), "local_config")
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME", "").strip()
    return (Path(configured) if configured else Path.home() / ".codex").resolve()


def _codex_auth_account() -> dict[str, str]:
    """Take the email domain from the identity token in Codex's `auth.json`.

    This file holds live credentials, so the handling is deliberately narrow.
    Only the `email` claim of `id_token` is used and the domain is all that is
    kept. Nothing else in the file is copied, stored, logged or sent, and an
    error here carries no content from it. The token's signature is not checked,
    so this is what the file says, not proof of who made a call. It stops on an
    API-key sign-in, and AGENTMETRY_CODEX_AUTH_DOMAIN=0 turns it off.
    """
    if os.environ.get("AGENTMETRY_CODEX_AUTH_DOMAIN", "").strip().lower() in _FALSE:
        return {}
    try:
        path = _codex_home() / "auth.json"
        if not path.is_file() or path.stat().st_size > _CODEX_AUTH_MAX_BYTES:
            return {}
        parsed = json.loads(path.read_bytes())
        if not isinstance(parsed, dict) or parsed.get("auth_mode") != "chatgpt":
            return {}
        tokens = parsed.get("tokens")
        id_token = tokens.get("id_token") if isinstance(tokens, dict) else None
        if not isinstance(id_token, str) or id_token.count(".") != 2:
            return {}
        part = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        email = claims.get("email") if isinstance(claims, dict) else None
        return account_from_email(email, "codex_auth")
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return {}


def _codex_session_file(home: Path, transcript_path: Any, session_id: Any) -> Path | None:
    """Find the session file, from the path the hook named or else from its ID.

    Windows tools can hand over the extended form of a path, which would not
    match Codex's home. A session with no usable path is found by its ID, which
    Codex puts in the file name.
    """
    if isinstance(transcript_path, str) and transcript_path.endswith(".jsonl"):
        text = transcript_path
        if text.startswith(_WINDOWS_EXTENDED_PREFIX):
            text = text[len(_WINDOWS_EXTENDED_PREFIX) :]
        path = Path(text).resolve()
        if path.is_relative_to(home) and path.is_file():
            return path
    session = _clean_id(session_id)
    if not session or not session.replace("-", "").isalnum():
        return None
    # sessions/YYYY/MM/DD/rollout-<time>-<session id>.jsonl
    for path in (home / "sessions").glob(f"*/*/*/rollout-*-{session}.jsonl"):
        return path.resolve()
    return None


def _codex_session_account(transcript_path: Any, session_id: Any = "") -> dict[str, str]:
    """Read Codex's account IDs from the first line of its session file.

    Hook input names the file, but that format is not a stable interface and
    can change between versions. Only a session file under Codex's own home is
    opened, so a crafted path cannot point the hook at another file. Nothing is
    read past the first line.
    """
    try:
        path = _codex_session_file(_codex_home(), transcript_path, session_id)
        if path is None:
            return {}
        with path.open("rb") as handle:
            line = handle.readline(_SESSION_META_MAX_BYTES + 1)
        if len(line) > _SESSION_META_MAX_BYTES:
            return {}
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("type") != "session_meta":
            return {}
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return {}
        return account_from_ids(
            payload.get("creator_account_id"), payload.get("creator_user_id"), "session_meta"
        )
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def account_for_hook(source_app: str, data: dict[str, Any]) -> dict[str, str]:
    """Extract an account claim for the agent that sent this hook payload."""
    source = source_app.strip().lower()
    if source == "cursor":
        email = data.get("user_email")
        if email is None:
            email = data.get("userEmail")
        return account_from_email(email, "hook_payload")
    if source == "claude":
        return _local_claude_account()
    if source == "codex":
        ids = _codex_session_account(data.get("transcript_path"), data.get("session_id"))
        signed_in = _codex_auth_account()
        return {**ids, **signed_in} if signed_in else ids
    if source == "antigravity":
        return _local_antigravity_account()
    return {}


def account_for_otel(attrs: dict[str, Any]) -> dict[str, str]:
    """Extract Claude's documented OpenTelemetry account attributes."""
    email = attrs.get("user.email")
    org = attrs.get("organization.id")
    return account_from_email(email, "otel", org) or account_from_organization(org, "otel")
