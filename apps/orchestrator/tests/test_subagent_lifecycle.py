"""Subagent lifecycle mapping — F6, F7, F8 from the 2026-07-20 review.

F6: SubagentStop mapped to session_end on the parent correlation, so ingest
    flushed the parent's pending approvals as inferred-denied mid-session.
F7: Claude Code spawns subagents through the Task tool and emits no
    SubagentStart, so the swarm rule was blind on the most used agent CLI.
F8: Kimi stream-json recorded every call as success and never closed the turn;
    the Interrupt hook was dropped.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from agentmetry.core.audit.detection.rules import rule_session_tool_burst, rule_subagent_swarm_burst

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _key: "")


# --- F6: SubagentStop is not a parent session_end ----------------------------

def test_claude_subagent_stop_is_not_a_session_end():
    payload = ingest.map_claude_hook("SubagentStop", {
        "session_id": "parent-sess",
        "agent_type": "explore",
    })
    assert payload["event_type"] != "session_end", "would flush parent approvals"
    assert payload["correlation_id"] == "parent-sess", "stays correlated to parent"
    assert payload["reason"].startswith("subagent_stop:")


def test_kimi_subagent_stop_is_not_a_session_end():
    payload = ingest.map_kimi_hook("SubagentStop", {
        "session_id": "parent-sess",
        "agent_type": "worker",
    })
    assert payload["event_type"] != "session_end"
    assert payload["reason"].startswith("subagent_stop:")


def test_claude_real_stop_still_ends_the_session():
    payload = ingest.map_claude_hook("Stop", {"session_id": "s1"})
    assert payload["event_type"] == "session_end"


def test_subagent_stop_does_not_count_as_a_spawn():
    """The swarm rule must not read a finish as a start."""
    from agentmetry.core.audit.external import build_external_canonical

    # Ten stops in a window must not trip the swarm rule.
    events = [build_external_canonical(
        ingest.map_kimi_hook("SubagentStop", {"session_id": "s1", "agent_type": f"w{i}"})
    ) for i in range(10)]
    assert rule_subagent_swarm_burst(events) == []


# --- F7: Claude Task feeds the swarm rule ------------------------------------

def test_claude_task_is_tagged_as_a_subagent_start():
    payload = ingest.map_claude_hook("PostToolUse", {
        "session_id": "s1",
        "tool_name": "Task",
        "tool_input": {"subagent_type": "code-reviewer"},
        "tool_response": "done",
    })
    assert payload["reason"] == "subagent_start:code-reviewer"


def test_claude_task_swarm_fires():
    from agentmetry.core.audit.external import build_external_canonical

    events = []
    for i in range(6):
        payload = ingest.map_claude_hook("PostToolUse", {
            "session_id": "s1",
            "tool_name": "Task",
            "tool_input": {"subagent_type": "explore"},
        })
        payload["timestamp_utc"] = f"2026-07-24T12:0{i}:00+00:00"
        events.append(build_external_canonical(payload))
    detections = rule_subagent_swarm_burst(events)
    assert len(detections) == 1
    assert detections[0].rule_id == "subagent-swarm-burst"


def test_ordinary_claude_tool_is_not_a_subagent():
    payload = ingest.map_claude_hook("PostToolUse", {
        "session_id": "s1",
        "tool_name": "Read",
        "tool_input": {"file_path": "README.md"},
    })
    assert not payload["reason"].startswith("subagent_start:")


def test_subagent_markers_excluded_from_session_tool_burst():
    """Swarm activity has its own rule; it must not also drive the generic
    tool-burst count (double jeopardy)."""
    from agentmetry.core.audit.external import build_external_canonical

    events = []
    for i in range(45):
        payload = ingest.map_claude_hook("PostToolUse", {
            "session_id": "s1",
            "tool_name": "Task",
            "tool_input": {"subagent_type": "w"},
        })
        payload["timestamp_utc"] = f"2026-07-24T12:00:{i:02d}+00:00"
        events.append(build_external_canonical(payload))
    # 45 subagent starts in a minute: swarm fires, generic tool-burst does not.
    assert rule_subagent_swarm_burst(events)
    assert rule_session_tool_burst(events) == []


# --- F8: Kimi Interrupt + stream-json outcomes -------------------------------

def test_kimi_interrupt_closes_the_session():
    payload = ingest.map_kimi_hook("Interrupt", {"session_id": "s1"})
    assert payload["event_type"] == "session_end"
    assert payload["reason"] == "interrupted"


def _run_stream(lines, monkeypatch):
    posted = []
    monkeypatch.setattr(ingest, "post_ingest", lambda p, quiet=False: posted.append(p) or True)
    monkeypatch.setattr(ingest, "_read_repo_env", lambda _k: "")
    monkeypatch.setenv("AGENTMETRY_CORRELATION_ID", "stream-sess")
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"))
    rc = ingest.stream_json_main("kimi")
    return rc, posted


def test_stream_json_failed_result_is_recorded_as_failed(monkeypatch):
    lines = [
        {"role": "assistant", "tool_calls": [
            {"id": "tc_1", "function": {"name": "Shell", "arguments": '{"command":"badcmd"}'}},
        ]},
        {"role": "tool", "tool_call_id": "tc_1", "is_error": True, "content": "command not found"},
    ]
    rc, posted = _run_stream(lines, monkeypatch)
    assert rc == 0
    tool_events = [p for p in posted if p.get("event_type") in ("tool_called", "tool_failed")]
    assert len(tool_events) == 1
    assert tool_events[0]["event_type"] == "tool_failed"
    assert tool_events[0]["outcome"] == "error"


def test_stream_json_successful_result_stays_success(monkeypatch):
    lines = [
        {"role": "assistant", "tool_calls": [
            {"id": "tc_1", "function": {"name": "Read", "arguments": '{"path":"x"}'}},
        ]},
        {"role": "tool", "tool_call_id": "tc_1", "content": "ok"},
    ]
    rc, posted = _run_stream(lines, monkeypatch)
    tool_events = [p for p in posted if p.get("event_type") in ("tool_called", "tool_failed")]
    assert tool_events[0]["event_type"] == "tool_called"
    assert tool_events[0]["outcome"] == "success"


def test_stream_json_unresolved_call_is_still_posted(monkeypatch):
    """A call whose result never arrives must not be dropped."""
    lines = [
        {"role": "assistant", "tool_calls": [
            {"id": "tc_1", "function": {"name": "Read", "arguments": "{}"}},
        ]},
    ]
    rc, posted = _run_stream(lines, monkeypatch)
    assert rc == 0
    assert any(p.get("event_type") == "tool_called" for p in posted)


def test_stream_json_emits_a_session_end(monkeypatch):
    lines = [
        {"role": "assistant", "tool_calls": [
            {"id": "tc_1", "function": {"name": "Read", "arguments": "{}"}},
        ]},
    ]
    rc, posted = _run_stream(lines, monkeypatch)
    assert any(p.get("event_type") == "session_end" for p in posted), "turn must close"


def test_stream_json_empty_input_posts_nothing(monkeypatch):
    rc, posted = _run_stream([{"role": "assistant", "content": "hi"}], monkeypatch)
    assert rc == 1
    assert not posted
