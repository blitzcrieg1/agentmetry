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
