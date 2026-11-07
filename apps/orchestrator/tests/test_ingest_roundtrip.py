"""Every field a capture surface sends must survive `ExternalIngestBody`.

Pydantic ignores unknown keys, silently. So an undeclared field is not an error
at ingest time. It is a feature that passes its unit tests, because those call
the ingest functions with a dict, and then vanishes at the HTTP boundary where
the real capture path lives.

This has happened twice.

`tool.traits` and `tool.mitre` were dropped first. The hook computes both from
the plaintext command before hashing it away, so dropping them made every
default-config event invisible to every command-based sequence rule. The rules
passed their tests, because the tests injected a `command` field that production
events did not have.

Then 0.6.0 shipped MCP per-tool digests and the initialize handshake, and
`schema_tool_digests`, `server_version`, `list_changed` and `initiator` were all
dropped the same way. The release headline, "a schema move names the tool that
moved", was true in the module and false over the wire.

Both bugs are the same bug. These tests build payloads with the real proxy
builders rather than hand-written dicts, so a field added to a builder without
being added to the model fails here instead of shipping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentmetry.api.routes.audit import ExternalIngestBody
from agentmetry.core.diagnostics.mcp_schema import fingerprint_each_tool, fingerprint_tools

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def _proxy():
    try:
        import mcp_audit_proxy
    except Exception as exc:  # pragma: no cover - import guard
        pytest.skip(f"mcp_audit_proxy not importable: {exc}")
    return mcp_audit_proxy


def _survives(payload: dict) -> dict:
    """What is left of a payload after the ingest model has parsed it."""
    return ExternalIngestBody(**payload).model_dump(exclude_none=True)


SAMPLE_TOOLS = [
    {"name": "send_email", "description": "Send an email", "inputSchema": {"type": "object"}},
    {"name": "list_templates", "description": "List templates"},
]


def test_every_key_the_schema_builder_emits_survives_ingest():
    """The structural guard. Catches the next dropped field, whatever it is."""
    proxy = _proxy()
    payload = proxy.build_schema_payload(
        "postmark",
        SAMPLE_TOOLS,
        "corr-1",
        server_version="1.4.2",
        list_changed=True,
    )
    kept = _survives(payload)
    missing = sorted(k for k in payload if k not in kept)
    assert not missing, (
        f"mcp_audit_proxy sends {missing} and ExternalIngestBody drops them. "
        "Declare the field on the model, or stop sending it."
    )


def test_every_key_the_call_builder_emits_survives_ingest():
    proxy = _proxy()
    payload = proxy.build_call_payload(
        {"method": "tools/call", "params": {"name": "send_email", "arguments": {"to": "a@b.c"}}},
        "postmark",
        "corr-2",
    )
    assert payload is not None
    kept = _survives(payload)
    missing = sorted(k for k in payload if k not in kept)
    assert not missing, (
        f"mcp_audit_proxy sends {missing} and ExternalIngestBody drops them."
    )


def test_per_tool_digests_reach_the_other_side():
    """The 0.6.0 headline, checked over the model rather than the module.

    Without this the digests are computed, POSTed, and discarded, and a schema
    move can only say which server changed.
    """
    payload = {
        "source_app": "mcp_proxy",
        "event_type": "mcp_schema",
        "schema_fingerprint": fingerprint_tools(SAMPLE_TOOLS),
        "schema_tool_count": len(SAMPLE_TOOLS),
        "schema_tool_digests": fingerprint_each_tool(SAMPLE_TOOLS),
        "server_version": "1.4.2",
        "list_changed": True,
    }
    kept = _survives(payload)
    assert kept["schema_tool_digests"] == payload["schema_tool_digests"]
    assert kept["server_version"] == "1.4.2"
    assert kept["list_changed"] is True


def test_initiator_survives_and_reaches_the_canonical_event():
    """`external.py` reads `payload["initiator"]`; the model used to hide it."""
    from agentmetry.core.audit.external import build_external_canonical

    payload = {
        "source_app": "mcp_proxy",
        "event_type": "tool_called",
        "tool_qualified": "postmark.send_email",
        "initiator": {"actor_type": "autonomous", "trigger": "cron", "operator_id": "svc"},
    }
    kept = _survives(payload)
    assert kept["initiator"]["actor_type"] == "autonomous"
    event = build_external_canonical(kept)
    assert event["initiator"]["actor_type"] == "autonomous"
    assert event["initiator"]["trigger"] == "cron"


def test_unknown_actor_type_falls_back_to_agent():
    """Coerced down, never up.

    `human` resets approval gates and `autonomous` is what
    `autonomous-unapproved-write` keys on, so an unrecognised string must not
    land on either. A new surface adds its kind to `_ACTOR_TYPES` deliberately.
    """
    kept = _survives(
        {
            "source_app": "cursor",
            "event_type": "tool_called",
            "initiator": {"actor_type": "definitely-not-a-real-kind"},
        }
    )
    assert kept["initiator"]["actor_type"] == "agent"


def test_client_cannot_assert_identity():
    """The lockdown that must not regress while opening `initiator`.

    `host_id` and `fleet_id` are stamped by the receiving orchestrator. Adding
    an actor field must not become a way to claim to be another machine.
    """
    kept = _survives(
        {
            "source_app": "cursor",
            "event_type": "tool_called",
            "host_id": "not-my-host",
            "fleet_id": "not-my-fleet",
        }
    )
    assert "host_id" not in kept
    assert "fleet_id" not in kept


# ---------------------------------------------------------------------------
# The hook's payloads. The third dropped-field bug was here: `classification`
# and `input_hash_alg` were set by the hook and read by external.py, and the
# tests for both called build_external_canonical with the hook's dict, which
# skipped this model. An outside audit found it over HTTP on 2026-11-02.
# ---------------------------------------------------------------------------

#: Keys the hook may send that the orchestrator recomputes rather than reads,
#: so dropping them at the model loses nothing. ATLAS is derived from `mitre`
#: on the receiving side (external.py), and an adapter's own value is not
#: honoured over HTTP.
_RECOMPUTED_TOOL_KEYS = frozenset({"atlas"})

#: Long enough to pass the hook's classification bound, so it is marked partial.
_OVERSIZED = "echo " + "z " * 5000


@pytest.fixture
def keyed_hook(monkeypatch: pytest.MonkeyPatch):
    from agentmetry.hooks import ingest

    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setenv("AGENTMETRY_HASH_KEY", "fleet-secret")
    monkeypatch.setenv("AGENTMETRY_LOG_FULL_ARGS", "1")
    return ingest


def _hook_payload(ingest, command: str) -> dict:
    payload = ingest.map_claude_hook(
        "PostToolUse",
        {
            "session_id": "roundtrip",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": "ok",
        },
    )
    assert payload is not None
    return ingest._hash_tool_args(payload)


def test_every_tool_key_the_hook_emits_survives_ingest(keyed_hook):
    """The structural guard for the hook, as the proxy tests above are for MCP.

    Keyed, full-argument, oversized: the configuration that sets the most keys.
    """
    payload = _hook_payload(keyed_hook, _OVERSIZED + " && cat ~/.aws/credentials")
    kept = _survives(payload)
    missing = sorted(k for k in payload if k not in kept)
    assert not missing, f"the hook sends {missing} and ExternalIngestBody drops them."
    tool_missing = sorted(
        k for k in payload["tool"] if k not in kept.get("tool", {}) and k not in _RECOMPUTED_TOOL_KEYS
    )
    assert not tool_missing, (
        f"the hook sends tool.{tool_missing} and IngestToolBody drops them. "
        "Declare the field on the model, or stop sending it."
    )


def test_partial_classification_reaches_the_stored_event(keyed_hook):
    """#348's marker, over the model: an empty trait list must not read as clean."""
    from agentmetry.core.audit.external import build_external_canonical

    payload = _hook_payload(keyed_hook, _OVERSIZED)
    assert payload["tool"]["classification"] == "partial"
    event = build_external_canonical(_survives(payload))
    assert event["tool"]["classification"] == "partial"


def test_a_keyed_digest_is_labelled_hmac_after_ingest(keyed_hook):
    """The digest was always keyed; the label said `hash` once it crossed HTTP."""
    from agentmetry.core.audit.external import build_external_canonical

    payload = _hook_payload(keyed_hook, "git status")
    assert payload["tool"]["input_hash_alg"] == "hmac-sha256"
    event = build_external_canonical(_survives(payload))
    assert event["tool"]["input_redaction"].split("+")[0] == "hmac"
    assert event["tool"]["input_hash"] == payload["tool"]["input_hash"]


# ---------------------------------------------------------------------------
# The reported model (#389). The fourth dropped field. The guard above only ran
# the Claude mapper, which sends no model, so Codex's nested `model` was lost
# over HTTP and the stored event said `codex` for both model and provider.
# ---------------------------------------------------------------------------


def _codex_payload(ingest, model: str = "glm-5.3") -> dict:
    payload = ingest.map_codex_hook(
        "PostToolUse",
        {
            "session_id": "roundtrip",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "model": model,
        },
    )
    assert payload is not None
    return ingest._hash_tool_args(payload)


def test_every_key_the_codex_hook_emits_survives_ingest(keyed_hook):
    payload = _codex_payload(keyed_hook)
    kept = _survives(payload)
    missing = sorted(k for k in payload if k not in kept)
    assert not missing, f"the Codex hook sends {missing} and ExternalIngestBody drops them."
    model_missing = sorted(k for k in payload["model"] if k not in kept["model"])
    assert not model_missing, f"the Codex hook sends model.{model_missing} and they are dropped."


def test_the_model_codex_reports_reaches_the_stored_event(keyed_hook):
    from agentmetry.core.audit.external import build_external_canonical

    event = build_external_canonical(_survives(_codex_payload(keyed_hook)))
    assert event["model"]["id"] == "glm-5.3"


def test_codex_does_not_mean_openai(keyed_hook):
    """Codex can point at any endpoint, so the harness says nothing about who serves it."""
    from agentmetry.core.audit.external import build_external_canonical

    payload = _codex_payload(keyed_hook)
    assert "provider" not in payload["model"]
    assert build_external_canonical(_survives(payload))["model"]["provider"] == "codex"


def test_a_provider_the_surface_states_is_kept():
    from agentmetry.core.audit.external import build_external_canonical

    kept = _survives(
        {
            "source_app": "codex",
            "event_type": "tool_called",
            "model": {"id": "glm-5.3", "provider": "selfhosted"},
        }
    )
    assert build_external_canonical(kept)["model"] == {"id": "glm-5.3", "provider": "selfhosted"}


def test_model_id_is_still_accepted():
    """OTel ingest and older clients send the flat field."""
    from agentmetry.core.audit.external import build_external_canonical

    kept = _survives({"source_app": "claude", "event_type": "tool_called", "model_id": "opus"})
    assert build_external_canonical(kept)["model"] == {"id": "opus", "provider": "claude"}


@pytest.mark.parametrize("bad", ["glm-5.3", 7, ["glm-5.3"], True])
def test_a_model_of_the_wrong_shape_is_ignored_not_rejected(bad):
    """Undeclared, this field was ignored. Declaring it must not start refusing events."""
    from agentmetry.core.audit.external import build_external_canonical

    kept = _survives({"source_app": "codex", "event_type": "tool_called", "model": bad})
    assert build_external_canonical(kept)["model"] == {"id": "codex", "provider": "codex"}


@pytest.mark.parametrize("bad", [7, ["x"], {"a": 1}, None])
def test_model_fields_of_the_wrong_type_fall_back(bad):
    from agentmetry.core.audit.external import build_external_canonical

    kept = _survives(
        {"source_app": "codex", "event_type": "tool_called", "model": {"id": bad, "provider": bad}}
    )
    assert build_external_canonical(kept)["model"] == {"id": "codex", "provider": "codex"}


def test_model_fields_are_bounded_on_both_ingest_paths():
    """HTTP passes this model and the spool replay does not, so the bound sits behind both."""
    from agentmetry.core.audit.external import build_external_canonical

    payload = {
        "source_app": "codex",
        "event_type": "tool_called",
        "model": {"id": "m" * 5000, "provider": "p" * 5000},
    }
    for event in (build_external_canonical(payload), build_external_canonical(_survives(payload))):
        assert event["model"]["id"] == "m" * 256
        assert event["model"]["provider"] == "p" * 256
