"""Tests for the investigation tree: `session_tree.fold` and GET /audit/session/{id}/tree."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentmetry.core.audit.session_tree import COMMAND_LIMIT, fold
from agentmetry.core.config import settings


def _ev(event_id, kind, ts, outcome="success", reason="", tool=None, **extra):
    event = {
        "event_id": event_id,
        "correlation_id": "sess-T",
        "timestamp_utc": f"2026-10-15T16:{ts}+00:00",
        "host_id": "HOST",
        "source": {"app": "cursor", "adapter": "cursor_hook"},
        "action": {"type": kind, "outcome": outcome, "reason": reason},
    }
    if tool is not None:
        event["tool"] = tool
    event.update(extra)
    return event


def _shell(qualified, input_hash, command=None):
    tool = {"qualified": qualified, "name": qualified.split(".")[-1], "server": "shell", "input_hash": input_hash}
    if command is not None:
        tool["command"] = command
    return tool


def test_ask_answer_and_call_fold_into_one_node_across_tool_names():
    """Cursor asks as cursor.Shell and runs as shell.run; the hash joins them."""
    nodes = fold([
        _ev("ask", "approval_request", "00:00", "pending", "decision:ask", _shell("cursor.Shell", "h1", "git push")),
        _ev("ans", "approval_response", "00:01", gated_action={"input_hash": "h1"}),
        _ev("call", "tool_called", "00:02", tool=_shell("shell.run", "h1")),
    ])
    assert len(nodes) == 1
    node = nodes[0]
    assert node["kind"] == "call"
    assert node["id"] == "call"
    assert node["event_ids"] == ["ask", "ans", "call"]
    assert node["approval"] == "approved"
    assert node["asked_as"] == "cursor.Shell"
    assert node["tool"]["qualified"] == "shell.run"
    assert node["tool"]["command"] == "git push"  # kept from the ask


def test_policy_verdicts_on_the_ask_land_on_the_call():
    dlp = {"rule_id": "agent_result_dump_dir", "mode": "log", "severity": "high"}
    policy = {"rule_id": "block_git_hook_persistence", "action": "deny", "mode": "log", "blocked": True}
    nodes = fold([
        _ev("ask", "approval_request", "00:00", "pending", tool=_shell("cursor.Shell", "h2"), dlp=dlp, tool_policy=policy),
        _ev("call", "tool_called", "00:01", tool=_shell("shell.run", "h2")),
    ])
    assert len(nodes) == 1
    assert nodes[0]["dlp"]["rule_id"] == "agent_result_dump_dir"
    assert nodes[0]["tool_policy"]["blocked"] is True


def test_a_denied_ask_stays_a_node_and_a_later_call_is_not_joined_to_it():
    nodes = fold([
        _ev("ask", "approval_request", "00:00", "pending", tool=_shell("cursor.Shell", "h3")),
        _ev("ans", "approval_response", "00:01", "denied", gated_action={"input_hash": "h3"}),
        _ev("call", "tool_called", "00:02", tool=_shell("shell.run", "h3")),
    ])
    assert [n["kind"] for n in nodes] == ["denied", "call"]
    assert nodes[0]["approval"] == "denied"
    assert nodes[0]["event_ids"] == ["ask", "ans"]
    assert nodes[1]["event_ids"] == ["call"]


def test_an_ask_closed_by_the_session_ending_is_expired_not_denied():
    """`inferred:session_ended_pending` is the recorder closing an open ask, not a refusal."""
    nodes = fold([
        _ev("ask", "approval_request", "00:00", "pending", tool=_shell("cursor.Shell", "h6")),
        _ev("ans", "approval_response", "00:01", "denied", "inferred:session_ended_pending", gated_action={"input_hash": "h6"}),
    ])
    assert nodes[0]["kind"] == "ask"
    assert nodes[0]["approval"] == "expired"
    assert nodes[0]["event_ids"] == ["ask", "ans"]


def test_an_inferred_answer_is_labelled_inferred_not_approved():
    nodes = fold([
        _ev("ask", "approval_request", "00:00", "pending", tool=_shell("cursor.Shell", "h4")),
        _ev("ans", "approval_response", "00:01", reason="inferred:tool_ran_after_ask", gated_action={"input_hash": "h4"}),
        _ev("call", "tool_called", "00:02", tool=_shell("shell.run", "h4")),
    ])
    assert nodes[0]["approval"] == "inferred"


def test_an_unanswered_ask_with_no_call_stays_asked():
    nodes = fold([_ev("ask", "approval_request", "00:00", "pending", tool=_shell("cursor.Shell", "h5"))])
    assert nodes[0]["kind"] == "ask"
    assert nodes[0]["approval"] == "asked"


def test_lifecycle_subagents_and_detections_are_their_own_nodes_and_heartbeats_go():
    nodes = fold([
        _ev("start", "session_start", "00:00"),
        _ev("hb", "heartbeat", "00:01"),
        _ev("sub", "tool_called", "00:02", reason="subagent_start:Explore", tool={"qualified": "claude.subagent.explore"}),
        _ev("stop", "tool_called", "00:03", reason="subagent_stop:Explore", tool={"qualified": "claude.subagent_stop.explore"}),
        _ev("det", "detection", "00:04", "critical", detection={
            "rule_id": "credential-exfil", "title": "Credential access followed by network egress",
            "severity": "critical", "event_ids": ["x", "y"], "technique_ids": ["T1552.001"], "tactic_ids": ["TA0006"],
        }),
    ])
    assert [n["kind"] for n in nodes] == ["session_start", "subagent_start", "subagent_stop", "detection"]
    assert nodes[-1]["detection"]["event_ids"] == ["x", "y"]


def test_no_command_appears_unless_the_trail_recorded_one_and_long_ones_are_cut():
    nodes = fold([
        _ev("a", "tool_called", "00:00", tool=_shell("shell.run", "")),
        _ev("b", "tool_called", "00:01", tool=_shell("shell.run", "", "x" * (COMMAND_LIMIT + 10))),
    ])
    assert "command" not in nodes[0]["tool"]
    assert len(nodes[1]["tool"]["command"]) == COMMAND_LIMIT
    assert nodes[1]["tool"]["command_truncated"] is True


@pytest.fixture
def long_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """2,100 heartbeats and 2,100 calls, then the call a detection cites."""
    events = []
    for i in range(2100):
        events.append(_ev(f"hb{i}", "heartbeat", "00:00"))
        events.append({**_ev(f"c{i}", "tool_called", "00:01", tool=_shell("shell.run", f"h{i}")),
                       "timestamp_utc": f"2026-10-15T16:00:01.{i:06d}+00:00"})
    events.append({**_ev("cited", "tool_called", "59:00", tool=_shell("shell.run", "hz", "git push"))})
    jsonl = tmp_path / "audit-forward.jsonl"
    jsonl.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "audit_export_path", jsonl)
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db

    reset_trail_db()
    get_trail_db().insert_batch(events)
    from agentmetry.api.main import app

    return TestClient(app)


def test_the_tree_reaches_a_cited_call_the_session_endpoint_cuts_off(long_session: TestClient):
    session = long_session.get("/api/v1/audit/session/sess-T").json()
    assert "cited" not in {e["event_id"] for e in session["events"]}  # why the tree exists

    body = long_session.get("/api/v1/audit/session/sess-T/tree").json()
    ids = {i for node in body["nodes"] for i in node["event_ids"]}
    assert "cited" in ids
    assert body["truncated"] is False
    assert body["summary"]["total"] == 4201
    assert body["summary"]["by_type"]["heartbeat"] == 2100
    assert body["summary"]["hosts"] == ["HOST"]
    assert body["summary"]["apps"] == ["cursor"]


def test_the_tree_says_when_it_was_cut(long_session: TestClient):
    body = long_session.get("/api/v1/audit/session/sess-T/tree?limit=100").json()
    assert body["truncated"] is True
    assert len(body["nodes"]) == 100


def test_a_session_longer_than_the_limit_is_windowed_on_the_detection(long_session: TestClient):
    """The oldest 100 calls would miss the cited one; a window around it does not."""
    body = long_session.get(
        "/api/v1/audit/session/sess-T/tree?limit=100&around_utc=2026-10-15T16:59:00%2B00:00"
    ).json()
    ids = [i for node in body["nodes"] for i in node["event_ids"]]
    assert "cited" in ids
    assert "c0" not in ids
    assert body["truncated"] is True
    assert len(body["nodes"]) == 100


def test_the_tree_of_an_unknown_session_is_empty(long_session: TestClient):
    body = long_session.get("/api/v1/audit/session/nope/tree").json()
    assert body["nodes"] == []
    assert body["summary"]["total"] == 0
