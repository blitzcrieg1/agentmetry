"""Tests for command-string secret scrubbing (Tier A/B command logging)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.audit.external import build_external_canonical
from core.audit.redaction import scrub_arg_values, scrub_secrets

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
import agentmetry_ingest as ingest  # noqa: E402


SECRET_CASES = [
    ("curl -H 'Authorization: Bearer sk-abc123DEF456ghi789JKL'", "sk-abc123DEF456ghi789JKL"),
    ("git push https://user:supersecret@github.com/x/y", "supersecret"),
    ("deploy --password hunter2taco --force", "hunter2taco"),
    ("export API_KEY=AKIAIOSFODNN7EXAMPLE && run", "AKIAIOSFODNN7EXAMPLE"),
    ("set token=ghp_0123456789abcdefghijABCDEFGHIJ012345", "ghp_0123456789abcdefghijABCDEFGHIJ012345"),
]


@pytest.mark.parametrize("cmd,secret", SECRET_CASES)
def test_scrub_secrets_masks(cmd, secret):
    out = scrub_secrets(cmd)
    assert secret not in out, f"secret leaked: {out}"


def test_scrub_preserves_benign_command():
    cmd = "git log --oneline -3 && pytest -q"
    assert scrub_secrets(cmd) == cmd


def test_scrub_arg_values_scrubs_command_key():
    args = {"command": "curl -H 'Authorization: Bearer sk-abcdef0123456789ABCDEF'", "description": "x"}
    out = scrub_arg_values(args)
    assert "sk-abcdef0123456789ABCDEF" not in out["command"]
    assert out["description"] == "x"


@pytest.mark.parametrize("cmd,secret", SECRET_CASES)
def test_client_and_server_scrubbers_agree(cmd, secret):
    """The inline hook mirror must match core/audit/redaction.py (no drift)."""
    assert ingest.scrub_command(cmd) == scrub_secrets(cmd)


def test_external_canonical_scrubs_stored_command():
    """A command with an inline secret is masked in the stored canonical event."""
    out = build_external_canonical({
        "source_app": "claude",
        "event_type": "tool_called",
        "correlation_id": "c1",
        "tool": {
            "qualified": "Bash",
            "server": "claude",
            "input_hash": "a" * 64,
            "command": "curl -H 'Authorization: Bearer sk-DEADbeef0123456789abcdef'",
            "arguments": {"command": "curl -H 'Authorization: Bearer sk-DEADbeef0123456789abcdef'"},
        },
    })
    assert "sk-DEADbeef0123456789abcdef" not in out["tool"]["command"]
    assert "sk-DEADbeef0123456789abcdef" not in str(out["tool"]["arguments"])
