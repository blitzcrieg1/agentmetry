"""StopFailure and SessionEnd for Claude Code.

Stop does not run when the person interrupts a turn, and an API error fires
StopFailure in its place (Claude Code hooks reference). With only Stop
registered, an approval ask left open by an interrupted or failed turn stayed
open until some later turn ended cleanly, or forever. Reported on r/ClaudeCode,
2026-11-13.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.hook_bootstrap import CLAUDE_HOOK_EVENTS
from agentmetry.core.audit.ingest import infer_approval_payloads, reset_pending_approvals

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")


def test_the_installer_registers_both_turn_ends():
    assert "StopFailure" in CLAUDE_HOOK_EVENTS
    assert "SessionEnd" in CLAUDE_HOOK_EVENTS


def test_stop_failure_ends_the_turn_with_the_error_type():
    payload = ingest.map_claude_hook("StopFailure", {
        "session_id": "s1",
        "hook_event_name": "StopFailure",
        "error": "rate_limit",
        "error_details": "429 Too Many Requests",
        "last_assistant_message": "API Error: Rate limit reached",
    })
    assert payload["event_type"] == "session_end"
    assert payload["correlation_id"] == "s1"
    assert payload["reason"] == "stop_failure:rate_limit"
    # The free-text fields are not recorded anywhere on the event.
    flat = repr(payload)
    assert "429" not in flat
    assert "Rate limit reached" not in flat


def test_session_end_keeps_its_reason():
    payload = ingest.map_claude_hook("SessionEnd", {
        "session_id": "s1", "hook_event_name": "SessionEnd", "reason": "prompt_input_exit",
    })
    assert payload["event_type"] == "session_end"
    assert payload["reason"] == "session_end:prompt_input_exit"


@pytest.mark.parametrize("hook,field", [("StopFailure", "error"), ("SessionEnd", "reason")])
@pytest.mark.parametrize("value", ["", "Rate Limit!", "x" * 41, "rm -rf /", None])
def test_a_value_outside_the_enum_shape_is_recorded_as_unknown(hook, field, value):
    data = {"session_id": "s1"}
    if value is not None:
        data[field] = value
    payload = ingest.map_claude_hook(hook, data)
    assert payload["reason"].endswith(":unknown")


@pytest.mark.parametrize("hook,data", [
    ("StopFailure", {"error": "overloaded"}),
    ("SessionEnd", {"reason": "other"}),
])
def test_an_ask_left_open_by_the_turn_is_closed(hook, data):
    """An ask with no result, then the turn ends without Stop: the ask closes."""
    reset_pending_approvals()
    infer_approval_payloads(build_external_canonical({
        "source_app": "claude", "event_type": "approval_request", "outcome": "pending",
        "correlation_id": "conv-turn-end",
        "tool": {"qualified": "Bash", "server": "shell", "input_hash": "a" * 64},
    }))

    end = ingest.map_claude_hook(hook, {"session_id": "conv-turn-end", **data})
    closed = infer_approval_payloads(build_external_canonical(end))

    assert len(closed) == 1
    assert closed[0]["reason"] == "inferred:session_ended_pending"
