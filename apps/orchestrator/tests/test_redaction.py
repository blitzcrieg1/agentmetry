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


# Prefixed assignments (2026-11-15). The key=value pattern required a word
# boundary right before the keyword, and `_` is a word character, so
# `HF_TOKEN=...`, `AWS_SECRET_ACCESS_KEY=...` and `?access_token=...` were
# stored as typed whenever command logging or full-argument capture was on.
# Values are built from pieces so no file holds a realistic secret.

_HF = "hf_" + "Q7" * 17
_AWS = "wJalr" + "XUtnF" * 6

PREFIXED_CASES = [
    ("HF_" + "TOKEN=" + _HF + " hf upload org/repo ./out", _HF),
    ("export HF_" + "TOKEN=" + _AWS, _AWS),
    ('export HF_' + 'TOKEN="' + _AWS + '"', _AWS),
    ("AWS_SECRET_" + "ACCESS_KEY=" + _AWS + " aws s3 ls", _AWS),
    ("DJANGO_SECRET_" + "KEY=" + _AWS + " python manage.py check", _AWS),
    ("curl 'https://example.com/api?access_" + "token=" + _AWS + "&page=2'", _AWS),
    ("python push.py --repo org/x " + _HF, _HF),
]


@pytest.mark.parametrize("cmd,secret", PREFIXED_CASES)
@pytest.mark.parametrize("scrub", [scrub_secrets, ingest.scrub_command], ids=["server", "hook"])
def test_a_prefixed_or_quoted_assignment_is_masked(scrub, cmd, secret):
    out = scrub(cmd)
    assert secret not in out, f"secret leaked: {out}"


@pytest.mark.parametrize("cmd,secret", PREFIXED_CASES)
def test_client_and_server_agree_on_prefixed_assignments(cmd, secret):
    assert ingest.scrub_command(cmd) == scrub_secrets(cmd)


@pytest.mark.parametrize("cmd", [
    "python train.py max_tokens=4000 tokenizer=bert",
    "HF_TOKEN_PATH=/tmp/cache hf whoami",
    "kubectl get secret prod-db -o yaml",
    "helm install app --set secret_name=prod-db",
    "curl 'https://example.com/api?page=2&limit=50'",
])
def test_names_that_only_contain_a_keyword_are_left_alone(cmd):
    assert scrub_secrets(cmd) == cmd
    assert ingest.scrub_command(cmd) == cmd


def test_the_name_is_kept_and_only_the_value_goes():
    out = scrub_secrets("HF_" + "TOKEN=" + _HF + " hf upload org/repo")
    assert out.startswith("HF_TOKEN=<redacted>")
    assert out.endswith("hf upload org/repo")


@pytest.mark.parametrize("scrub", [scrub_secrets, ingest.scrub_command], ids=["server", "hook"])
def test_a_long_command_scrubs_quickly(scrub):
    """The hook classifies up to 8 KiB; the wider name prefix must stay linear."""
    import time

    for chunk in ("a_" * 4096, "a=" * 4096, "x" * 8192, "token_" * 1365):
        start = time.perf_counter()
        scrub(chunk)
        assert time.perf_counter() - start < 1.0


# --- every token format the detection rules name is scrubbed (0.13.0) -----------

import re  # noqa: E402

from agentmetry.core.audit import redaction as _redaction  # noqa: E402
from agentmetry.core.audit.detection.traits import _ISSUERS  # noqa: E402

_A, _H = "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC2dF4", "0123456789abcdef"
ISSUER_SAMPLES = {
    "huggingface": ["hf_" + _A],
    "github": ["ghp_" + _A + "xyz", "github_pat_" + (_A + "_") * 2],
    "gitlab": ["glpat-" + _A[:20]],
    "npm": ["npm_" + _A + "xyz"],
    "pypi": ["pypi-" + _A * 2],
    "openai": ["sk-proj-" + _A + "_x-" + _A[:6], "sk-svcacct-" + _A],
    "anthropic": ["sk-ant-api03-" + _A],
    "aws": ["ASIA" + "QWERTY234567ABCD", "AKIA" + "QWERTY234567ABCD"],
    "docker": ["dckr_pat_" + _A[:27]],
    "google": ["AIza" + _A + "_x"],
    "slack": ["xoxb-1234567890-1234567890-" + _A[:24], "xapp-1-A0123BCD-4567-" + _H * 4],
    "stripe": ["sk_live_" + _A[:24], "rk_test_" + _A[:24]],
    "sendgrid": ["SG." + _A[:22] + "." + (_A + _A)[:43]],
    "shopify": ["shpat_" + _H * 2],
    "digitalocean": ["dop_v1_" + _H * 4],
    "linear": ["lin_api_" + (_A * 2)[:40]],
    "doppler": ["dp.pt." + (_A * 2)[:43]],
    "postman": ["PMAK-" + (_H * 2)[:24] + "-" + (_H * 3)[:34]],
    "pulumi": ["pul-" + (_H * 3)[:40]],
    "databricks": ["dapi" + _H * 2],
}


def test_every_issuer_has_a_redaction_sample():
    """A provider added to the detection rules must be added here, and to redaction."""
    assert set(ISSUER_SAMPLES) == set(_ISSUERS)


@pytest.mark.parametrize(
    "provider, token", [(p, t) for p, ts in ISSUER_SAMPLES.items() for t in ts]
)
def test_issuer_tokens_are_scrubbed_by_both_copies(provider, token):
    assert re.fullmatch(_ISSUERS[provider][1], token), (provider, token)
    # Not a NAME=value assignment, so only the format patterns can catch it.
    command = f"curl -s https://api.example.net/v1/check -d {token} | jq ."
    for scrubbed in (scrub_secrets(command), ingest.scrub_command(command)):
        assert token not in scrubbed, (provider, scrubbed)
        assert "api.example.net/v1/check" in scrubbed


def test_hook_mirror_carries_the_same_patterns():
    server = [(p.pattern, p.flags, r) for p, r in _redaction._SECRET_PATTERNS]
    client = [(p.pattern, p.flags, r) for p, r in ingest._SECRET_PATTERNS]
    assert server == client


@pytest.mark.parametrize(
    "command",
    [
        "git log --oneline -3 && pytest -q",
        "sha256sum dist/agentmetry-0.13.0.tar.gz",
        "git show 3f9c2a1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39",
        "python -m pip install skl2onnx sk-video",
        "aws s3 ls s3://bucket/path --region eu-west-1",
    ],
)
def test_ordinary_text_survives_scrubbing(command):
    assert scrub_secrets(command) == command
    assert ingest.scrub_command(command) == command
