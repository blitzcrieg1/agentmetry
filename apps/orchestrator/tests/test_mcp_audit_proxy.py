"""Tests for the MCP audit proxy payload builders (F6)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(_TOOLS))

proxy = importlib.import_module("mcp_audit_proxy")


def test_call_payload_uses_session_correlation_not_jsonrpc_id():
    """correlation_id must be the stable session id, never the JSON-RPC request id."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "read_note", "arguments": {"path": "x.md"}}}
    payload = proxy.build_call_payload(msg, "vault_fs", "sess-abc")
    assert payload is not None
    assert payload["correlation_id"] == "sess-abc"       # not "1"
    assert payload["tool"]["qualified"] == "vault_fs.read_note"
    # Args hashed in-proxy — no plaintext arguments in the payload (F4 consistency).
    assert "arguments" not in payload["tool"]
    assert len(payload["tool"]["input_hash"]) == 64


def test_call_payload_none_for_non_call():
    msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    assert proxy.build_call_payload(msg, "vault_fs", "sess-abc") is None


def test_call_payload_preserves_already_qualified_name():
    msg = {"method": "tools/call", "params": {"name": "mcp__x.read", "arguments": {}}}
    payload = proxy.build_call_payload(msg, "vault_fs", "s")
    assert payload["tool"]["qualified"] == "mcp__x.read"


def test_error_response_becomes_tool_failed():
    resp = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}}
    ctx = {"qualified": "vault_fs.read_note", "server": "vault_fs"}
    payload = proxy.build_error_payload(resp, ctx, "sess-abc")
    assert payload is not None
    assert payload["event_type"] == "tool_failed"
    assert payload["outcome"] == "error"
    assert payload["reason"] == "boom"
    assert payload["correlation_id"] == "sess-abc"


def test_success_response_is_not_an_error():
    resp = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    assert proxy.build_error_payload(resp, {"qualified": "t", "server": "s"}, "s") is None


def test_correlation_env_override(monkeypatch):
    monkeypatch.setenv("AGENTMETRY_CORRELATION_ID", "fixed-corr")
    assert proxy._correlation_id() == "fixed-corr"
