"""Every hook decision in the exact shape the calling agent enforces.

Until 0.9.0 the hook sent Cursor's `{"permission": "deny"}` to every agent but
Antigravity. Claude Code does not recognise a top-level `permission` key, so it
treated the exit-0 hook as success and ran the tool. The same process had
already written that call to the trail as `outcome: denied`.

So the control failed open, the tamper-evident record said it had worked, and
three tests asserted the wrong format, which meant CI certified it. A string
match on `"permission": "deny"` cannot tell a format the agent honours from one
it silently ignores.

These tests parse the output and assert the documented schema per agent, so a
format that drifts fails here rather than in an incident.

Schemas, from each vendor's hook documentation:

  Claude Code PreToolUse       hookSpecificOutput.permissionDecision  allow|deny|ask
  Claude Code PermissionRequest hookSpecificOutput.decision.behavior  allow|deny, no ask
  Cursor                        top-level permission                   allow|deny|ask
  Antigravity                   top-level decision
  Codex                         Claude-shaped, strict; see the Codex section

Codex was the one agent the 0.9.0 fix missed. It kept receiving Cursor's key,
and its parser rejects unknown fields, so every deny ran the tool.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402

CLAUDE_PROTOCOL = ("claude", "qwen", "qoder", "codebuddy", "kimi")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "post_ingest", lambda *a, **k: True)
    monkeypatch.setattr(ingest, "dlp_scan", lambda *a, **k: SimpleNamespace(matched=False))
    monkeypatch.delenv("AGENTMETRY_ENFORCE", raising=False)


def _decision(monkeypatch, source: str, hook: str, decision: str, reason: str = "") -> dict:
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", source)
    return ingest._decision_output(hook, decision, reason)


# --- the regression ---------------------------------------------------------


def test_claude_pre_tool_use_deny_is_the_shape_claude_enforces(monkeypatch):
    out = _decision(monkeypatch, "claude", "PreToolUse", "deny", "dlp:aws_key")
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "dlp:aws_key",
        }
    }


def test_claude_is_never_sent_the_cursor_key(monkeypatch):
    """The exact defect. `permission` at top level is Cursor's, and Claude ignores it."""
    for decision in ("allow", "deny", "ask"):
        out = _decision(monkeypatch, "claude", "PreToolUse", decision)
        assert "permission" not in out, decision


@pytest.mark.parametrize("source", CLAUDE_PROTOCOL)
def test_every_claude_protocol_agent_gets_hook_specific_output(monkeypatch, source):
    out = _decision(monkeypatch, source, "PreToolUse", "deny")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "permission" not in out


def test_claude_ask_reaches_the_native_prompt(monkeypatch):
    out = _decision(monkeypatch, "claude", "PreToolUse", "ask")
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_reason_is_omitted_rather_than_sent_empty(monkeypatch):
    out = _decision(monkeypatch, "claude", "PreToolUse", "deny")
    assert "permissionDecisionReason" not in out["hookSpecificOutput"]


# --- PermissionRequest has no ask -------------------------------------------


def test_permission_request_uses_decision_behavior(monkeypatch):
    out = _decision(monkeypatch, "claude", "PermissionRequest", "deny")
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny"},
        }
    }


def test_permission_request_ask_becomes_deny_never_allow(monkeypatch):
    """The event takes allow|deny only. An ask has to resolve to one of them.

    Deny is the only defensible direction for a security control. Resolving it
    to allow would be precisely the silent failure this file exists to avoid.
    """
    out = _decision(monkeypatch, "claude", "PermissionRequest", "ask")
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_permission_request_allow_is_allow(monkeypatch):
    out = _decision(monkeypatch, "claude", "PermissionRequest", "allow")
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "allow"


# --- agents whose format already worked must not change ----------------------


@pytest.mark.parametrize("decision", ["allow", "deny", "ask"])
def test_cursor_output_is_unchanged(monkeypatch, decision):
    """Cursor's format was correct before this fix. Byte-identical is the point."""
    out = _decision(monkeypatch, "cursor", "beforeShellExecution", decision, "dlp:aws_key")
    assert out == {"permission": decision}


def test_antigravity_output_is_unchanged(monkeypatch):
    assert _decision(monkeypatch, "antigravity", "PreToolUse", "deny") == {"decision": "deny"}


# --- Codex: checked against its own schema and parser rules ------------------
#
# Codex parses hook stdout with `deny_unknown_fields` (openai/codex
# codex-rs/hooks, 806d2d1). Anything it cannot parse, or parses and rejects,
# marks the hook `Failed` and the tool runs. So a shape check is not enough:
# these validate against Codex's published schema, then apply the parser's
# rejections that the schema cannot express.

_CODEX_SCHEMAS = Path(__file__).parent / "fixtures" / "codex_hooks"


def _codex_blocks(hook: str, out: dict) -> bool:
    """What Codex does with this output: True blocks, False runs the tool.

    Raises if Codex would mark the hook `Failed`, which also runs the tool, but
    is a malformed decision rather than a deliberate allow.
    """
    import jsonschema

    name = {"PreToolUse": "pre-tool-use", "PermissionRequest": "permission-request"}[hook]
    schema = json.loads((_CODEX_SCHEMAS / f"{name}.command.output.schema.json").read_text())
    jsonschema.validate(out, schema)
    specific = out.get("hookSpecificOutput") or {}
    if hook == "PermissionRequest":
        return (specific.get("decision") or {}).get("behavior") == "deny"
    decision = specific.get("permissionDecision")
    if decision == "ask":
        raise AssertionError("Codex rejects permissionDecision:ask")
    if decision == "allow" and "updatedInput" not in specific:
        raise AssertionError("Codex rejects permissionDecision:allow without updatedInput")
    if decision == "deny":
        if not str(specific.get("permissionDecisionReason") or "").strip():
            raise AssertionError("Codex rejects a deny without a non-empty reason")
        return True
    return False


def test_codex_is_never_sent_the_cursor_key(monkeypatch):
    """The defect: Codex rejected `permission` as an unknown field and ran the tool."""
    import jsonschema

    old = {"permission": "deny"}
    schema = json.loads((_CODEX_SCHEMAS / "pre-tool-use.command.output.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(old, schema)
    for hook in ("PreToolUse", "PermissionRequest"):
        for decision in ("allow", "deny", "ask"):
            assert "permission" not in _decision(monkeypatch, "codex", hook, decision), (hook, decision)


@pytest.mark.parametrize("hook", ["PreToolUse", "PermissionRequest"])
@pytest.mark.parametrize("reason", ["dlp:aws_key", ""])
def test_codex_deny_blocks(monkeypatch, hook, reason):
    """Including an empty reason, which Codex would otherwise reject as a fail-open."""
    assert _codex_blocks(hook, _decision(monkeypatch, "codex", hook, "deny", reason))


@pytest.mark.parametrize("hook", ["PreToolUse", "PermissionRequest"])
def test_codex_ask_becomes_deny_never_allow(monkeypatch, hook):
    """Codex marks an ask `Failed` and runs the tool, so an ask has to be a deny."""
    assert _codex_blocks(hook, _decision(monkeypatch, "codex", hook, "ask", "tool_policy:x"))


@pytest.mark.parametrize("hook", ["PreToolUse", "PermissionRequest"])
def test_codex_allow_is_a_clean_allow(monkeypatch, hook):
    assert not _codex_blocks(hook, _decision(monkeypatch, "codex", hook, "allow"))


def test_codex_deny_keeps_the_rule_in_the_reason(monkeypatch):
    out = _decision(monkeypatch, "codex", "PreToolUse", "deny", "tool_policy:block_shell_rm")
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "tool_policy:block_shell_rm"
    out = _decision(monkeypatch, "codex", "PermissionRequest", "deny", "dlp:aws_key")
    assert out["hookSpecificOutput"]["decision"]["message"] == "dlp:aws_key"


def test_a_real_policy_block_on_codex_blocks(monkeypatch, capsys):
    """End to end through hook_main, with Codex's own Bash tool input."""
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "codex")
    _block(monkeypatch, "block_shell_rm")
    monkeypatch.setattr(
        ingest,
        "read_hook_stdin",
        lambda: ({"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
                  "tool_input": {"command": "rm -rf /"}}, False),
    )
    ingest.hook_main("PreToolUse")
    out = _last_json(capsys)
    assert _codex_blocks("PreToolUse", out)
    assert out["hookSpecificOutput"]["permissionDecisionReason"] == "tool_policy:block_shell_rm"


# --- through the real hook path ---------------------------------------------


def _block(monkeypatch, rule_id: str = "block_shell_rm"):
    monkeypatch.setattr(
        ingest,
        "tool_policy_eval",
        lambda *a, **k: SimpleNamespace(
            matched=True,
            blocked=True,
            mode="block",
            match=SimpleNamespace(rule_id=rule_id, action="deny"),
        ),
    )


def _last_json(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_a_real_policy_block_on_claude_carries_the_rule(monkeypatch, capsys):
    """End to end through hook_main, and the reason names what fired."""
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    _block(monkeypatch, "block_shell_rm")
    monkeypatch.setattr(
        ingest,
        "read_hook_stdin",
        lambda: ({"session_id": "s1", "tool_name": "Bash",
                  "tool_input": {"command": "rm -rf /"}}, False),
    )
    ingest.hook_main("PreToolUse")
    out = _last_json(capsys)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert out["permissionDecisionReason"] == "tool_policy:block_shell_rm"


def test_the_enforce_override_uses_the_agent_format(monkeypatch, capsys):
    """`AGENTMETRY_ENFORCE` took the same broken path and gets the same fix."""
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    monkeypatch.setenv("AGENTMETRY_ENFORCE", "deny")
    monkeypatch.setattr(ingest, "tool_policy_eval", None)
    monkeypatch.setattr(
        ingest,
        "read_hook_stdin",
        lambda: ({"session_id": "s1", "tool_name": "Bash",
                  "tool_input": {"command": "ls"}}, False),
    )
    ingest.hook_main("PreToolUse")
    out = _last_json(capsys)
    assert "permission" not in out
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_an_after_hook_still_emits_nothing(monkeypatch, capsys):
    """Unchanged: a block on PostToolUse is recorded, never turned into a deny."""
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    _block(monkeypatch)
    monkeypatch.setattr(
        ingest,
        "read_hook_stdin",
        lambda: ({"session_id": "s1", "tool_name": "Bash",
                  "tool_input": {"command": "rm -rf /"}, "exit_code": 0}, False),
    )
    ingest.hook_main("PostToolUse")
    assert capsys.readouterr().out.strip() == ""
