"""What the Claude Code adapter records before a call, for a prompt, and for a subagent.

All payloads are authored fixtures in the shape of Claude Code's hook input.
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.hook_bootstrap import CLAUDE_HOOK_EVENTS
from agentmetry.core.audit.ingest import infer_approval_payloads, reset_pending_approvals
from agentmetry.hooks import ingest


@pytest.fixture(autouse=True)
def _isolated_hook(monkeypatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")
    monkeypatch.setattr(ingest, "account_for_hook", lambda *_args: None)
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "claude")
    monkeypatch.delenv("AGENTMETRY_ADAPTER", raising=False)
    reset_pending_approvals()
    yield
    reset_pending_approvals()


def _pre_tool_use(**extra):
    return ingest.map_claude_hook("PreToolUse", {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "permission_mode": "acceptEdits",
        "tool_name": "Bash",
        "tool_input": {"command": "printf synthetic"},
        "tool_use_id": "toolu_synthetic_001",
        **extra,
    })


def test_pre_tool_use_records_no_decision_that_claude_did_not_send():
    """Claude Code's PreToolUse input has no decision, so none is recorded."""
    payload = _pre_tool_use()
    assert payload["event_type"] == "approval_request"
    assert payload["outcome"] == "pending"
    assert payload["reason"] == "hook:PreToolUse;permission_mode:acceptEdits"
    assert "decision:" not in payload["reason"]


def test_pre_tool_use_without_permission_mode_records_none():
    """A harness that reports no mode is not recorded as running in one."""
    payload = ingest.map_claude_hook("PreToolUse", {
        "session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": "README.md"},
    })
    assert payload["reason"] == "hook:PreToolUse"


@pytest.mark.parametrize(
    "permission_mode", ["default;decision:allow", "plan:x", "a b", "x" * 41],
)
def test_pre_tool_use_permission_mode_cannot_add_reason_fields(permission_mode):
    payload = _pre_tool_use(permission_mode=permission_mode)
    assert payload["reason"] == "hook:PreToolUse;permission_mode:unknown"


@pytest.mark.parametrize(
    ("decision", "outcome"), [("ask", "pending"), ("deny", "denied"), ("allow", "success")],
)
def test_pre_tool_use_keeps_a_decision_that_a_caller_sends(decision, outcome):
    payload = _pre_tool_use(permissionDecision=decision)
    assert payload["outcome"] == outcome
    assert payload["reason"] == f"decision:{decision};hook:PreToolUse"


def _notification(notification_type):
    data = {
        "hook_event_name": "Notification",
        "session_id": "s1",
        "message": "synthetic notification",
    }
    if notification_type is not None:
        data["notification_type"] = notification_type
    return ingest.map_claude_hook("Notification", data)


def test_a_permission_prompt_is_an_approval_request():
    payload = _notification("permission_prompt")
    assert payload["event_type"] == "approval_request"
    assert payload["outcome"] == "pending"
    assert payload["reason"] == "hook:Notification;notification_type:permission_prompt"


@pytest.mark.parametrize(
    "notification_type", ["idle_prompt", "auth_success", "elicitation_dialog", "", None],
)
def test_a_notification_that_asks_nothing_is_not_recorded(notification_type):
    assert _notification(notification_type) is None


def test_a_permission_prompt_does_not_end_as_an_inferred_denial():
    """A prompt names no tool, so no call answers it and no denial is inferred."""
    prompt = build_external_canonical(_notification("permission_prompt"))
    request = build_external_canonical(_pre_tool_use())
    result = build_external_canonical(ingest.map_claude_hook("PostToolUse", {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "printf synthetic"},
        "tool_use_id": "toolu_synthetic_001",
        "tool_response": {"stdout": ""},
    }))
    end = build_external_canonical(ingest.map_claude_hook("Stop", {
        "hook_event_name": "Stop", "session_id": "s1",
    }))
    assert infer_approval_payloads(prompt) == []
    assert infer_approval_payloads(request) == []
    assert [p["reason"] for p in infer_approval_payloads(result)] == [
        "inferred:tool_ran_after_ask",
    ]
    assert infer_approval_payloads(end) == []


def test_an_unanswered_call_request_still_ends_as_an_inferred_denial():
    """Only the prompt is exempt. A call request with a tool keeps its inference."""
    request = build_external_canonical(_pre_tool_use())
    end = build_external_canonical(ingest.map_claude_hook("Stop", {
        "hook_event_name": "Stop", "session_id": "s1",
    }))
    assert infer_approval_payloads(request) == []
    assert [p["reason"] for p in infer_approval_payloads(end)] == [
        "inferred:session_ended_pending",
    ]


@pytest.mark.parametrize("tool_name", ["Task", "Agent"])
def test_a_spawned_subagent_is_a_subagent_start(tool_name):
    """Current Claude Code names its subagent tool Agent, earlier ones Task."""
    payload = ingest.map_claude_hook("PostToolUse", {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "tool_name": tool_name,
        "tool_input": {"subagent_type": "Explore", "prompt": "synthetic"},
        "tool_response": {"status": "completed"},
    })
    assert payload["outcome"] == "success"
    assert payload["reason"] == "subagent_start:Explore"


def test_notification_stays_installed():
    """It is the only hook that says a person was shown a permission prompt."""
    assert "Notification" in CLAUDE_HOOK_EVENTS
