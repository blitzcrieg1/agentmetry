"""Per-fleet keyed argument hashing (pilot hardening item 11).

Tool arguments leave the hook as a 64-hex fingerprint. Plain SHA-256 of a
guessable argument is a lookup away: anyone with SIEM read access can hash
`git push --force` and find every event that ran it. With AGENTMETRY_HASH_KEY
set the fingerprint is HMAC-SHA256 under that key and `input_redaction` says
"hmac". The fingerprint is still 64 hex and still deterministic within the
fleet, so detections that compare `input_hash` (the approval-gate rule) are
unchanged, and the ruleset fingerprint does not move.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from agentmetry.core.config import settings
from agentmetry.hooks import ingest

_ARGS = {"command": "git push --force"}


def _blob(args: dict) -> bytes:
    clean = ingest.redact_arguments(args)
    return json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode()


@pytest.fixture
def no_repo_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.delenv("AGENTMETRY_HASH_KEY", raising=False)
    monkeypatch.setattr(settings, "hash_key", "")


def test_without_a_key_the_digest_is_unchanged(no_repo_env):
    """Existing trails and SIEM correlations must keep matching."""
    assert ingest.hash_arguments(_ARGS) == hashlib.sha256(_blob(_ARGS)).hexdigest()


def test_with_a_key_the_digest_is_an_hmac(no_repo_env, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HASH_KEY", "fleet-secret")
    expected = hmac.new(b"fleet-secret", _blob(_ARGS), hashlib.sha256).hexdigest()
    digest = ingest.hash_arguments(_ARGS)
    assert digest == expected
    assert digest != hashlib.sha256(_blob(_ARGS)).hexdigest(), "a dictionary of plain hashes must not match"
    assert len(digest) == 64


def test_the_same_argument_matches_across_the_fleet(no_repo_env, monkeypatch):
    """Two hosts with the same key: the approval-gate comparison still holds."""
    monkeypatch.setenv("AGENTMETRY_HASH_KEY", "fleet-secret")
    assert ingest.hash_arguments(_ARGS) == ingest.hash_arguments(dict(_ARGS))


def test_two_fleets_do_not_correlate(no_repo_env, monkeypatch):
    monkeypatch.setenv("AGENTMETRY_HASH_KEY", "fleet-a")
    a = ingest.hash_arguments(_ARGS)
    monkeypatch.setenv("AGENTMETRY_HASH_KEY", "fleet-b")
    assert ingest.hash_arguments(_ARGS) != a


def test_the_hook_reads_the_key_from_the_repo_env(monkeypatch):
    monkeypatch.delenv("AGENTMETRY_HASH_KEY", raising=False)
    monkeypatch.setattr(ingest, "_read_repo_env", lambda key: "from-env-file" if key == "AGENTMETRY_HASH_KEY" else "")
    expected = hmac.new(b"from-env-file", _blob(_ARGS), hashlib.sha256).hexdigest()
    assert ingest.hash_arguments(_ARGS) == expected


def test_a_keyed_hook_says_so_and_the_event_is_labelled_hmac(no_repo_env, monkeypatch):
    from agentmetry.core.audit.external import build_external_canonical

    monkeypatch.setenv("AGENTMETRY_HASH_KEY", "fleet-secret")
    payload = {"source_app": "cursor", "tool": {"qualified": "shell.run", "arguments": dict(_ARGS)}}
    hashed = ingest._hash_tool_args(payload)
    assert hashed["tool"]["input_hash_alg"] == "hmac-sha256"
    event = build_external_canonical(hashed)
    assert event["tool"]["input_redaction"].split("+")[0] == "hmac"
    assert event["tool"]["input_hash"] == hashed["tool"]["input_hash"]


def test_an_unkeyed_hook_is_labelled_hash(no_repo_env):
    from agentmetry.core.audit.external import build_external_canonical

    payload = {"source_app": "cursor", "tool": {"qualified": "shell.run", "arguments": dict(_ARGS)}}
    hashed = ingest._hash_tool_args(payload)
    assert "input_hash_alg" not in hashed["tool"]
    assert build_external_canonical(hashed)["tool"]["input_redaction"].split("+")[0] == "hash"


def test_the_orchestrator_keys_a_digest_it_computes_itself(no_repo_env, monkeypatch):
    """Plaintext arguments from an external client are fingerprinted server-side."""
    from agentmetry.core.audit.external import build_external_canonical
    from agentmetry.core.audit.hashing import canonical_json

    monkeypatch.setattr(settings, "hash_key", "server-secret")
    event = build_external_canonical({"source_app": "custom", "tool": {"qualified": "fs.read", "arguments": {"path": "/etc/passwd"}}})
    expected = hmac.new(b"server-secret", canonical_json({"path": "/etc/passwd"}).encode(), hashlib.sha256).hexdigest()
    assert event["tool"]["input_hash"] == expected
    assert event["tool"]["input_redaction"] == "hmac"


def test_the_key_never_appears_in_the_settings_repr(monkeypatch):
    monkeypatch.setattr(settings, "hash_key", "do-not-log-me")
    assert "do-not-log-me" not in repr(settings)


def test_doctor_warns_on_an_unkeyed_fleet(no_repo_env, monkeypatch):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_hashing

    monkeypatch.setattr(settings, "fleet_id", "eu-pilot")
    report = DoctorReport()
    _check_hashing(report)
    assert report.findings[-1].severity == "warn"


def test_doctor_is_ok_on_a_keyed_fleet(no_repo_env, monkeypatch):
    from agentmetry.core.diagnostics.doctor import DoctorReport, _check_hashing

    monkeypatch.setattr(settings, "fleet_id", "eu-pilot")
    monkeypatch.setattr(settings, "hash_key", "fleet-secret")
    report = DoctorReport()
    _check_hashing(report)
    assert report.findings[-1].severity == "ok"
    assert "fleet-secret" not in report.findings[-1].message

