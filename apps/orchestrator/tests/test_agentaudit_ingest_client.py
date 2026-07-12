"""Tests for scripts/agentaudit_ingest.py hook mappers."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentaudit_ingest as ingest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_repo_env(monkeypatch):
    """Prevent live apps/orchestrator/.env from changing hash/log behavior in tests."""
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")

def test_cursor_before_mcp_maps_approval_request():
    payload = ingest.map_cursor_hook("beforeMCPExecution", {
        "conversation_id": "conv-1",
        "tool_name": "read_file",
        "mcp_server": "vault_fs",
        "tool_input": {"path": "foo.md"},
        "permission": "ask",
    })
    assert payload is not None
    assert payload["event_type"] == "approval_request"
    assert payload["tool"]["qualified"] == "vault_fs.read_file"
    assert "decision:ask" in payload["reason"]


def test_cursor_post_tool_redacts_secrets():
    payload = ingest.map_cursor_hook("postToolUse", {
        "conversation_id": "conv-2",
        "tool_name": "Shell",
        "tool_input": {"command": "echo hi", "api_key": "secret"},
    })
    assert payload["tool"]["arguments"]["api_key"] == "<redacted>"


def test_claude_pre_tool_use():
    payload = ingest.map_claude_hook("PreToolUse", {
        "session_id": "sess-claude",
        "tool_name": "mcp__vault__read",
        "tool_input": {"path": "x"},
        "permissionDecision": "ask",
    })
    assert payload["source_app"] == "claude"
    assert payload["event_type"] == "approval_request"


def test_antigravity_post_tool():
    payload = ingest.map_antigravity_hook("PostToolUse", {
        "conversationId": "ag-conv",
        "toolName": "run_command",
        "toolInput": {"command": "ls"},
    })
    assert payload["source_app"] == "antigravity"
    assert payload["tool"]["qualified"] == "antigravity.run_command"


def test_antigravity_v2_pre_tool_use_run_command(monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "antigravity")
    payload = ingest.map_hook("PreToolUse", {
        "toolCall": {
            "name": "run_command",
            "args": {
                "CommandLine": "Get-Process | Sort-Object CPU -Descending | Select-Object -First 5",
                "Cwd": r"C:\Users\spiro\.gemini\antigravity\scratch",
            },
        },
        "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",
        "stepIdx": 3,
    })
    assert payload is not None
    assert payload["tool"]["qualified"] == "antigravity.run_command"
    assert len(payload["tool"]["input_hash"]) == 64


def test_antigravity_v2_post_tool_use_step_only():
    payload = ingest.map_antigravity_hook("PostToolUse", {
        "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",
        "stepIdx": 3,
        "error": "",
    })
    assert payload is not None
    assert payload["event_type"] == "tool_called"
    assert "step:3" in payload["reason"]


def test_codex_bash_post_tool():
    payload = ingest.map_codex_hook("PostToolUse", {
        "session_id": "codex-sess-1",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "model": "gpt-5.4-codex",
    })
    assert payload["source_app"] == "codex"
    assert payload["tool"]["qualified"] == "shell.run"
    assert payload["model"]["id"] == "gpt-5.4-codex"


def test_codex_permission_request():
    payload = ingest.map_codex_hook("PermissionRequest", {
        "session_id": "codex-sess-2",
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /tmp/x"},
        "permission_mode": "default",
        "model": "gpt-5.4-codex",
    })
    assert payload["event_type"] == "approval_request"
    assert payload["outcome"] == "pending"


def test_codex_mcp_tool_name():
    payload = ingest.map_codex_hook("PostToolUse", {
        "session_id": "s1",
        "tool_name": "mcp__vault_fs__read_note",
        "tool_input": {"path": "foo.md"},
        "model": "gpt-5.4-codex",
    })
    assert payload["tool"]["qualified"] == "vault_fs.read_note"
    assert payload["tool"]["server"] == "vault_fs"


def test_redact_and_hash_stable():
    h1 = ingest.hash_arguments({"a": 1, "token": "x"})
    h2 = ingest.hash_arguments({"a": 1, "token": "y"})
    assert h1 == h2


def test_map_hook_hashes_and_strips_plaintext_args(monkeypatch):
    """Wire path must send input_hash only — never plaintext arguments (F4)."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    payload = ingest.map_hook("postToolUse", {
        "conversation_id": "c1",
        "tool_name": "Shell",
        "tool_input": {"command": "echo hi", "token": "secret"},
    })
    assert payload is not None
    assert "arguments" not in payload["tool"]
    assert len(payload["tool"]["input_hash"]) == 64
    assert "command" not in payload["tool"]


def test_map_hook_keeps_command_when_enabled(monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "codex")
    monkeypatch.setenv("AGENTAUDIT_LOG_COMMANDS", "1")
    payload = ingest.map_hook("PostToolUse", {
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q"},
    })
    assert payload is not None
    assert payload["tool"]["command"] == "pytest -q"
    assert "arguments" not in payload["tool"]


def test_read_hook_stdin_utf16_le(monkeypatch):
    payload = {"conversation_id": "utf16", "command": "Get-Location", "exit_code": 0}
    raw = json.dumps(payload).encode("utf-16-le")
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(raw)})())

    data, decode_error = ingest.read_hook_stdin()
    assert data["command"] == "Get-Location"
    assert decode_error is True  # non-utf-8 encoding used


def test_read_hook_stdin_utf16_le_bom(monkeypatch):
    payload = {"conversation_id": "bom", "command": "dir"}
    raw = b"\xff\xfe" + json.dumps(payload).encode("utf-16-le")
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(raw)})())

    data, decode_error = ingest.read_hook_stdin()
    assert data["command"] == "dir"


def test_read_hook_stdin_empty():
    old = sys.stdin
    sys.stdin = type("S", (), {"buffer": io.BytesIO(b"")})()
    try:
        data, decode_error = ingest.read_hook_stdin()
        assert data == {}
        assert decode_error is False
    finally:
        sys.stdin = old


def test_extract_command_all_adapters():
    assert ingest.extract_command({"command": "dir"}, "shell.run") == "dir"
    assert ingest.extract_command({"command": "ls"}, "antigravity.run_command") == "ls"
    assert ingest.extract_command({"path": "x.md"}, "Read") == "x.md"


def test_map_hook_full_args_redacts_secrets(monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    monkeypatch.setenv("AGENTAUDIT_LOG_FULL_ARGS", "1")
    payload = ingest.map_hook("postToolUse", {
        "conversation_id": "c1",
        "tool_name": "Shell",
        "tool_input": {"command": "echo hi", "token": "secret"},
    })
    assert payload is not None
    assert payload["tool"]["arguments"]["token"] == "<redacted>"
    assert payload["tool"]["arguments"]["command"] == "echo hi"
    assert payload["tool"]["command"] == "echo hi"


def test_adapter_override_from_env(monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "antigravity")
    monkeypatch.setenv("AGENTAUDIT_ADAPTER", "antigravity_transcript")
    payload = ingest.map_hook("PreToolUse", {
        "toolCall": {"name": "run_command", "args": {"CommandLine": "dir"}},
        "conversationId": "c1",
    })
    assert payload is not None
    assert payload["adapter"] == "antigravity_transcript"

def test_after_hook_flags_failure(monkeypatch):
    """A failed tool must not be logged as success (F3)."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    payload = ingest.map_cursor_hook("afterShellExecution", {
        "conversation_id": "c1",
        "command": "false",
        "exit_code": 1,
    })
    assert payload["event_type"] == "tool_failed"
    assert payload["outcome"] == "error"
    assert "exit:1" in payload["reason"]


def test_after_hook_success_when_clean(monkeypatch):
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    payload = ingest.map_cursor_hook("afterShellExecution", {
        "conversation_id": "c1",
        "command": "echo hi",
        "exit_code": 0,
    })
    assert payload["event_type"] == "tool_called"
    assert payload["outcome"] == "success"


def test_hook_main_observe_only_no_auto_allow(monkeypatch, capsys):
    """Default install must not emit an allow decision (F1 security footgun)."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    monkeypatch.delenv("AGENTAUDIT_ENFORCE", raising=False)
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(
        ingest,
        "read_hook_stdin",
        lambda: ({"conversation_id": "c1", "tool_name": "Shell",
                  "command": "rm -rf x", "permission": "ask"}, False),
    )
    ingest.hook_main("beforeShellExecution")
    out = capsys.readouterr().out
    assert "permission" not in out


def test_selftest_green(monkeypatch, capsys):
    """Round-trip succeeds when the POSTed nonce comes back in the tail (F5)."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    captured: dict[str, str] = {}

    def fake_post(payload, **_kw):
        captured["corr"] = payload["correlation_id"]
        return True

    monkeypatch.setattr(ingest, "post_ingest", fake_post)
    monkeypatch.setattr(
        ingest, "_get_tail",
        lambda src, limit=50: {"events": [{"correlation_id": captured["corr"]}]},
    )
    assert ingest.selftest() == 0
    assert "GREEN" in capsys.readouterr().out


def test_selftest_red_when_post_fails(monkeypatch):
    """RED when the orchestrator is unreachable (F5)."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: False)
    assert ingest.selftest() == 1


def test_selftest_red_when_not_in_tail(monkeypatch):
    """RED when the event POSTs but never lands (ingest disabled / sink off)."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(ingest, "_get_tail", lambda src, limit=50: {"events": []})
    assert ingest.selftest() == 1


def test_hook_main_enforce_opt_in(monkeypatch, capsys):
    """Explicit opt-in still allows emitting a decision."""
    monkeypatch.setenv("AGENTAUDIT_SOURCE_APP", "cursor")
    monkeypatch.setenv("AGENTAUDIT_ENFORCE", "allow")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(
        ingest,
        "read_hook_stdin",
        lambda: ({"conversation_id": "c1", "tool_name": "Shell",
                  "command": "ls", "permission": "ask"}, False),
    )
    ingest.hook_main("beforeShellExecution")
    out = capsys.readouterr().out
    assert '"permission": "allow"' in out
