"""Account-domain capture is additive, bounded and redacted by default."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.api.routes.audit import ExternalIngestBody
from agentmetry.core.account import account_from_email, account_from_domain
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.config import settings


_CLAUDE_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "ANTHROPIC_ORGANIZATION_ID",
    "CLAUDE_CONFIG_DIR",
)


@pytest.fixture(autouse=True)
def _clear_claude_environment(monkeypatch: pytest.MonkeyPatch):
    for key in _CLAUDE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _survives(payload: dict) -> dict:
    return ExternalIngestBody(**payload).model_dump(exclude_none=True)


def test_cursor_hook_real_route_stores_only_the_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from agentmetry.core.audit.ingest import reset_ingest_sink_cache
    from agentmetry.core.audit.trail_db import reset_trail_db
    from agentmetry.hooks import ingest as hook

    jsonl = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_ingest_enabled", True)
    monkeypatch.setattr(settings, "audit_sink", "file")
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "trusted_hosts", "testserver")
    monkeypatch.setattr(settings, "auth_disabled", True)
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "cursor")
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    reset_trail_db()
    reset_ingest_sink_cache()

    payload = hook.map_hook(
        "sessionStart",
        {"conversation_id": "acct-route", "user_email": "dev@example.com"},
    )
    assert payload is not None
    assert payload["account"] == {"domain": "example.com", "source": "hook_payload"}
    from agentmetry.api.main import app

    response = TestClient(app).post("/api/v1/audit/ingest", json=payload)
    assert response.status_code == 200
    stored = json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])
    assert stored["event"]["account"] == payload["account"]
    assert "dev@example.com" not in jsonl.read_text(encoding="utf-8")


def test_spool_replay_path_keeps_the_same_account_block(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    payload = {
        "source_app": "cursor",
        "event_type": "tool_called",
        "account": {"domain": "example.com", "source": "hook_payload", "email": "dev@example.com"},
    }
    direct = build_external_canonical(payload)
    replay = build_external_canonical(_survives(payload))
    assert direct["account"] == replay["account"] == {
        "domain": "example.com",
        "source": "hook_payload",
    }


def test_full_email_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", "1")
    assert account_from_email("dev@example.com", "hook_payload") == {
        "domain": "example.com",
        "source": "hook_payload",
        "email": "dev@example.com",
    }
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    assert account_from_domain("example.com", "hook_payload", email="dev@example.com") == {
        "domain": "example.com",
        "source": "hook_payload",
    }


@pytest.mark.parametrize(
    "bad",
    [None, 7, "no-at", "a@b@c", "DEV@EXAMPLE.COM.", "a\x00@b.com", "a @b.com", "a@" + "x" * 254 + ".com"],
)
def test_malformed_account_claims_are_absent_and_never_a_422(bad):
    assert account_from_email(bad, "hook_payload") == {}
    kept = _survives(
        {
            "source_app": "cursor",
            "event_type": "session_start",
            "account": {"domain": "", "source": "hook_payload", "email": bad},
        }
    )
    assert build_external_canonical(kept).get("account") is None


def test_account_field_is_structurally_declared_and_bounded(monkeypatch: pytest.MonkeyPatch):
    from agentmetry.hooks import ingest as hook

    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "cursor")
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    payload = hook.map_hook(
        "afterFileEdit",
        {"conversation_id": "acct-guard", "user_email": "dev@example.com", "tool_name": "Read"},
    )
    assert payload is not None
    kept = _survives(payload)
    assert sorted(k for k in payload if k not in kept) == []
    assert build_external_canonical(kept)["account"]["domain"] == "example.com"


def test_old_payload_without_account_remains_valid():
    event = build_external_canonical({"source_app": "cursor", "event_type": "session_start"})
    assert "account" not in event


def test_claude_otel_claim_and_sink_adapters():
    from agentmetry.core.audit.adapters.chronicle import canonical_to_udm
    from agentmetry.core.audit.adapters.ecs import canonical_to_ecs
    from agentmetry.core.audit.otel_ingest import _base

    payload = _base(
        {"session.id": "otel-acct", "user.email": "dev@example.com", "organization.id": "org-1"},
        "2026-01-01T00:00:00+00:00",
    )
    event = build_external_canonical(payload)
    assert event["account"] == {
        "domain": "example.com",
        "source": "otel",
        "organization_id": "org-1",
    }
    ecs = canonical_to_ecs(event)
    assert "domain" not in ecs["user"]
    assert "email" not in ecs["user"]
    assert ecs["agentmetry"]["account"]["domain"] == "example.com"
    assert ecs["agentmetry"]["account"]["organization_id"] == "org-1"
    labels = {item["key"]: item["value"] for item in canonical_to_udm(event)["additional"]["labels"]}
    assert labels["agent_account_domain"] == "example.com"
    assert labels["agent_account_organization_id"] == "org-1"


def test_claude_local_config_fallback_reads_only_the_selected_account_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "dev@example.com", "organizationUuid": "org-local", "organizationName": "Example"}, "other": "ignored"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    claim = account.account_for_hook("claude", {"session_id": "local-config"})
    assert claim == {"domain": "example.com", "source": "local_config", "organization_id": "org-local"}


def test_claude_local_config_organization_survives_without_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"organizationUuid": "org-only"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    claim = account.account_for_hook("claude", {"session_id": "org-only-session"})
    assert claim == {
        "organization_id": "org-only",
        "source": "local_config",
    }
    event = build_external_canonical(
        {"source_app": "claude", "event_type": "session_start", "account": claim}
    )
    assert event["account"] == claim


def test_claude_local_config_is_not_cached_between_short_lived_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import agentmetry.core.account as account

    config = tmp_path / ".claude.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    config.write_text(json.dumps({"oauthAccount": {"emailAddress": "one@example.com"}}), encoding="utf-8")
    first = account.account_for_hook("claude", {"session_id": "short-lived-1"})
    config.write_text(json.dumps({"oauthAccount": {"emailAddress": "two@other.example"}}), encoding="utf-8")
    second = account.account_for_hook("claude", {"session_id": "short-lived-2"})
    assert first["domain"] == "example.com"
    assert second["domain"] == "other.example"


@pytest.mark.parametrize(
    "override",
    ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"],
)
def test_claude_local_config_is_skipped_for_auth_or_endpoint_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str,
):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "dev@example.com"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    monkeypatch.setenv(override, "synthetic-override")
    assert account.account_for_hook("claude", {"session_id": "override"}) == {}


def test_claude_official_base_url_keeps_the_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "dev@example.com"}}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    assert account.account_for_hook("claude", {}) == {"domain": "example.com", "source": "local_config"}


@pytest.mark.parametrize(
    "base_url",
    ["https://gateway.example", "https://api.anthropic.com.evil.example", "not a url"],
)
def test_claude_non_official_or_malformed_base_url_skips_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_url: str,
):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "dev@example.com"}}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)
    assert account.account_for_hook("claude", {}) == {}


@pytest.mark.parametrize(
    "override",
    [
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_PROFILE",
    ],
)
def test_claude_additional_credential_overrides_skip_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, override: str,
):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "dev@example.com"}}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv(override, "1")
    assert account.account_for_hook("claude", {}) == {}


def test_claude_federation_pair_requires_both_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import agentmetry.core.account as account

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "dev@example.com"}}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("ANTHROPIC_FEDERATION_RULE_ID", "rule")
    assert account.account_for_hook("claude", {})["domain"] == "example.com"
    monkeypatch.setenv("ANTHROPIC_ORGANIZATION_ID", "org")
    assert account.account_for_hook("claude", {}) == {}


def test_claude_config_dir_selects_the_signed_in_account_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import agentmetry.core.account as account

    config_dir = tmp_path / "claude-work"
    config_dir.mkdir()
    (config_dir / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "work@example.com"}}),
        encoding="utf-8",
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "personal@example.com"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    assert account.account_for_hook("claude", {"session_id": "config-dir"}) == {
        "domain": "example.com",
        "source": "local_config",
    }
