"""Validate and minimise the account identity a coding agent reports.

This module deliberately has no Agentmetry imports. Hook processes import it
before the receiver, and a malformed account claim must never break capture.
The value is a client claim, not proof of identity.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_EMAIL_MAX = 320
_DOMAIN_MAX = 253
_ORG_MAX = 256
_SOURCE_MAX = 32
_TRUE = frozenset({"1", "true", "yes", "on"})
_LOCAL_CONFIG_MAX_BYTES = 1024 * 1024
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


def account_from_claim(
    domain: Any,
    source: Any,
    organization_id: Any = "",
    email: Any = "",
    *,
    include_email: bool | None = None,
) -> dict[str, str]:
    """Keep a valid domain claim, or retain a valid organization-only claim."""
    account = account_from_domain(
        domain, source, organization_id, email, include_email=include_email
    )
    return account or account_from_organization(organization_id, source)


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


def account_for_hook(source_app: str, data: dict[str, Any]) -> dict[str, str]:
    """Extract an account claim from a documented hook payload."""
    source = source_app.strip().lower()
    if source == "cursor":
        email = data.get("user_email")
        if email is None:
            email = data.get("userEmail")
        return account_from_email(email, "hook_payload")
    if source == "claude":
        return _local_claude_account()
    return {}


def account_for_otel(attrs: dict[str, Any]) -> dict[str, str]:
    """Extract Claude's documented OpenTelemetry account attributes."""
    email = attrs.get("user.email")
    org = attrs.get("organization.id")
    return account_from_email(email, "otel", org) or account_from_organization(org, "otel")
