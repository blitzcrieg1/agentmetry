"""Tests for command-string secret scrubbing (Tier A/B command logging)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.redaction import scrub_arg_values, scrub_secrets

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


# Nested secrets (outside audit, 2026-11-02). With AGENTMETRY_LOG_FULL_ARGS on,
# key redaction and pattern scrubbing stopped at the top level of the
# arguments, so a token one level down was stored as sent.

_NESTED = {
    "nested": {"token": "AUDIT_NESTED_SECRET", "note": "Bearer sk-NESTEDabcdef0123456789xyz"},
    "items": [{"password": "in-a-list"}, "export API_KEY=AKIAIOSFODNN7EXAMPLE"],
    "path": "src/main.py",
}
_NESTED_SECRETS = (
    "AUDIT_NESTED_SECRET",
    "sk-NESTEDabcdef0123456789xyz",
    "in-a-list",
    "AKIAIOSFODNN7EXAMPLE",
)


@pytest.mark.parametrize("scrub", [scrub_arg_values, ingest.scrub_arg_values], ids=["server", "hook"])
def test_secrets_are_masked_at_every_depth(scrub):
    out = scrub(_NESTED)
    for secret in _NESTED_SECRETS:
        assert secret not in str(out), f"{secret} survived: {out}"
    assert out["path"] == "src/main.py"
    assert out["nested"]["token"] == "<redacted>"


@pytest.mark.parametrize("scrub", [scrub_arg_values, ingest.scrub_arg_values], ids=["server", "hook"])
def test_a_structure_deeper_than_the_walk_is_replaced_not_kept(scrub):
    deep: dict = {"token": "TOO_DEEP_SECRET"}
    for _ in range(100):
        deep = {"a": deep}
    assert "TOO_DEEP_SECRET" not in str(scrub(deep))


def test_client_and_server_redact_the_same_keys():
    from agentmetry.core.audit import redaction

    assert redaction.REDACT_KEYS == ingest.REDACT_KEYS
    assert redaction.SCRUB_MAX_DEPTH == ingest.SCRUB_MAX_DEPTH


def test_full_argument_capture_keeps_no_nested_secret_end_to_end(monkeypatch):
    """Hook, ingest model, canonical event: the path the audit reproduced."""
    from agentmetry.api.routes.audit import ExternalIngestBody

    monkeypatch.setenv("AGENTMETRY_LOG_FULL_ARGS", "1")
    payload = ingest._hash_tool_args(
        {"source_app": "claude", "event_type": "tool_called",
         "tool": {"qualified": "audit.tool", "arguments": dict(_NESTED)}}
    )
    wire = ExternalIngestBody.model_validate(payload).model_dump(exclude_none=True)
    stored = build_external_canonical(wire)["tool"]
    for secret in _NESTED_SECRETS:
        assert secret not in str(stored), f"{secret} stored: {stored}"


def test_the_digest_does_not_move_when_storage_redaction_got_deeper(monkeypatch):
    """Fingerprints must match across versions; only the stored copy changed."""
    import hashlib
    import json

    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.delenv("AGENTMETRY_HASH_KEY", raising=False)
    blob = json.dumps(ingest.redact_arguments(_NESTED), sort_keys=True, separators=(",", ":"), default=str)
    assert ingest.hash_arguments(_NESTED) == hashlib.sha256(blob.encode()).hexdigest()
