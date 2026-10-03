"""Machine-wide installs (pilot hardening items 15 and 18, the core half).

The MSI runs the recorder as a service account with its data in
%ProgramData%\\Agentmetry, readable only by administrators and the service.
Developers' hooks run as each developer, so they need two things the core
did not give them: a spool they are allowed to write, and a credential that
can send events without reading the trail. The enterprise extension supplies
that credential; the core decides where both live and that the hook uses them.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentmetry.core import api_token
from agentmetry.core.paths import hook_spool_path


@pytest.fixture
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in (
        "AGENTMETRY_HOOK_SPOOL_PATH", "AGENTMETRY_API_KEY", "BLACKBOX_API_KEY",
        "AGENTMETRY_TOKEN_SHARED", "AGENTMETRY_AUDIT_EXPORT_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTMETRY_API_TOKEN_FILE", str(tmp_path / "api-token"))
    monkeypatch.setenv("AGENTMETRY_INGEST_TOKEN_FILE", str(tmp_path / "ingest-token"))
    return tmp_path


# --- the spool ---------------------------------------------------------------


def test_the_spool_sits_beside_the_trail_by_default(tmp_path: Path, clean_env):
    assert hook_spool_path(tmp_path) == tmp_path / "hook-spool.jsonl"


def test_hook_and_drain_agree_on_a_relocated_spool(tmp_path: Path, clean_env, monkeypatch):
    """A hook writing a spool the drain never reads loses every deferred event."""
    from agentmetry.core.audit import spool
    from agentmetry.core.config import settings
    from agentmetry.hooks import ingest

    target = tmp_path / "hook" / "hook-spool.jsonl"
    monkeypatch.setenv("AGENTMETRY_HOOK_SPOOL_PATH", str(target))
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "trail" / "audit-forward.jsonl")
    monkeypatch.setenv("AGENTMETRY_AUDIT_EXPORT_PATH", str(tmp_path / "trail" / "audit-forward.jsonl"))
    assert ingest._spool_path() == target
    assert spool.spool_path() == target


def test_heartbeat_counts_the_relocated_spool(tmp_path: Path, clean_env, monkeypatch):
    from agentmetry.core.audit import heartbeat
    from agentmetry.core.config import settings

    target = tmp_path / "hook" / "hook-spool.jsonl"
    target.parent.mkdir()
    target.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    monkeypatch.setenv("AGENTMETRY_HOOK_SPOOL_PATH", str(target))
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "audit-forward.jsonl")
    assert heartbeat._spool_depth() == 2


# --- the ingest-only token ---------------------------------------------------


def test_the_hook_prefers_the_ingest_token(clean_env, monkeypatch):
    """Under Enterprise the full core token is not an enterprise token at all."""
    from agentmetry.hooks import ingest

    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    api_token.ensure_token()
    api_token.write_ingest_token("ingest-only")
    assert ingest._api_key() == "ingest-only"


def test_without_one_the_hook_uses_the_full_token(clean_env, monkeypatch):
    from agentmetry.hooks import ingest

    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    token = api_token.ensure_token()
    assert ingest._api_key() == token


def test_the_cli_never_uses_the_ingest_token(clean_env):
    """Admin commands need the full token; an ingest-only one would only 403."""
    api_token.write_ingest_token("ingest-only")
    assert api_token.client_token() == ""


def test_the_ingest_token_is_replaced_whole(clean_env):
    first = api_token.write_ingest_token("one")
    api_token.write_ingest_token("two")
    assert first.read_text(encoding="utf-8") == "two"
    assert not first.with_name(first.name + ".tmp").exists()


def test_a_single_user_install_keeps_it_owner_only(clean_env):
    path = api_token.write_ingest_token("ingest-only")
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    assert api_token.is_private(path) is not False


@pytest.mark.skipif(os.name != "nt", reason="the Windows ACL path")
def test_a_shared_install_lets_local_users_read_it(clean_env, monkeypatch):
    import subprocess

    monkeypatch.setenv("AGENTMETRY_TOKEN_SHARED", "1")
    path = api_token.write_ingest_token("ingest-only")
    acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False).stdout.lower()
    assert "users" in acl
