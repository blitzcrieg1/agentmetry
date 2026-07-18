"""A `block` verdict may only deny on a genuinely pre-execution hook.

High #1 from the 2026-07-18 review: on an after-hook (afterShellExecution,
PostToolUse, ...) the tool has already run, so printing a deny decision is a
false prevention guarantee. Enforcement must fire only on pre-hooks; on
after-hooks the match is recorded but never turned into a deny.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Hermetic: no live .env, no network POST, DLP inert (tool policy drives)."""
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(ingest, "dlp_scan", lambda *a, **k: SimpleNamespace(matched=False))
    monkeypatch.delenv("AGENTMETRY_ENFORCE", raising=False)


def _block_verdict(rule_id: str = "block_shell_rm"):
    return SimpleNamespace(
        matched=True,
        blocked=True,
        mode="block",
        match=SimpleNamespace(rule_id=rule_id, action="deny"),
    )


def _force_block(monkeypatch):
    monkeypatch.setattr(ingest, "tool_policy_eval", lambda *a, **k: _block_verdict())


# --- after-hooks must NOT deny (the tool already ran) ------------------------

def test_cursor_after_shell_block_does_not_deny(monkeypatch, capsys):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "cursor")
    _force_block(monkeypatch)
    monkeypatch.setattr(
        ingest, "read_hook_stdin",
        lambda: ({"conversation_id": "c1", "tool_name": "Shell",
                  "command": "rm -rf /", "exit_code": 0}, False),
    )
    ingest.hook_main("afterShellExecution")
    out = capsys.readouterr().out
    assert "deny" not in out
    assert "permission" not in out


def test_claude_post_tool_use_block_does_not_deny(monkeypatch, capsys):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    _force_block(monkeypatch)
    monkeypatch.setattr(
        ingest, "read_hook_stdin",
        lambda: ({"session_id": "s1", "tool_name": "Bash",
                  "tool_input": {"command": "rm -rf /"}, "exit_code": 0}, False),
    )
    ingest.hook_main("PostToolUse")
    out = capsys.readouterr().out
    assert "deny" not in out


def test_antigravity_post_tool_use_block_does_not_deny(monkeypatch, capsys):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "antigravity")
    _force_block(monkeypatch)
    monkeypatch.setattr(
        ingest, "read_hook_stdin",
        lambda: ({"conversationId": "ag1", "toolName": "run_command",
                  "toolInput": {"command": "rm -rf /"}}, False),
    )
    ingest.hook_main("PostToolUse")
    out = capsys.readouterr().out
    assert "deny" not in out


# --- pre-hooks still deny (the tool has not run yet) -------------------------

def test_cursor_before_shell_block_emits_deny(monkeypatch, capsys):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "cursor")
    _force_block(monkeypatch)
    monkeypatch.setattr(
        ingest, "read_hook_stdin",
        lambda: ({"conversation_id": "c1", "tool_name": "Shell",
                  "command": "rm -rf /", "permission": "ask"}, False),
    )
    ingest.hook_main("beforeShellExecution")
    out = capsys.readouterr().out
    assert '"permission": "deny"' in out


def test_claude_pre_tool_use_block_emits_deny(monkeypatch, capsys):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    _force_block(monkeypatch)
    monkeypatch.setattr(
        ingest, "read_hook_stdin",
        lambda: ({"session_id": "s1", "tool_name": "Bash",
                  "tool_input": {"command": "rm -rf /"}, "permissionDecision": "ask"}, False),
    )
    ingest.hook_main("PreToolUse")
    out = capsys.readouterr().out
    assert '"permission": "deny"' in out


def test_antigravity_pre_tool_use_block_emits_deny(monkeypatch, capsys):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "antigravity")
    _force_block(monkeypatch)
    monkeypatch.setattr(
        ingest, "read_hook_stdin",
        lambda: ({"conversationId": "ag1", "toolName": "run_command",
                  "toolInput": {"command": "rm -rf /"}}, False),
    )
    ingest.hook_main("PreToolUse")
    out = capsys.readouterr().out
    assert '"decision": "deny"' in out
