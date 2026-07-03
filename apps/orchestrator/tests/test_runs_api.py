"""Tests for run history summarization and node-event persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.graphs.node_events as node_events_module
from api.routes.runs import read_jsonl_tail, summarize_runs
from core.graphs.node_events import emit_node


def test_read_jsonl_tail_skips_corrupt_lines(tmp_path: Path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"a": 1}\nnot json\n{"b": 2}\n', encoding="utf-8")
    assert read_jsonl_tail(path) == [{"a": 1}, {"b": 2}]


def test_read_jsonl_tail_missing_file(tmp_path: Path):
    assert read_jsonl_tail(tmp_path / "missing.jsonl") == []


def test_summarize_runs_collapses_lifecycle_events():
    events = [
        {"ts": "t1", "thread_id": "x", "skill": "lead_gen", "status": "waiting_for_input",
         "triggered_by": "manual"},
        {"ts": "t2", "thread_id": "y", "skill": "summarize_meeting", "status": "completed",
         "triggered_by": "vault_watch", "cost": 0.01},
        {"ts": "t3", "thread_id": "x", "skill": "lead_gen", "status": "approved",
         "cost": 0.02, "latency_ms": 1200, "archive_path": "30-Archive/a.md"},
    ]
    records = summarize_runs(events)

    # One record per thread, newest first.
    assert [r["thread_id"] for r in records] == ["y", "x"]
    lead_gen = records[1]
    assert lead_gen["status"] == "approved"  # later event wins
    assert lead_gen["started"] == "t1"
    assert lead_gen["updated"] == "t3"
    assert lead_gen["triggered_by"] == "manual"  # earlier field retained
    assert lead_gen["archive_path"] == "30-Archive/a.md"


def test_summarize_runs_keeps_anonymous_events():
    events = [
        {"ts": "t1", "skill": "lead_gen", "status": "rejected", "error": "LLM degraded"},
        {"ts": "t2", "skill": "lead_gen", "status": "rejected", "error": "LLM degraded"},
    ]
    records = summarize_runs(events)
    assert len(records) == 2
    assert all(r["thread_id"] is None for r in records)


async def test_emit_node_persists_thread_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    events_file = tmp_path / "node-events.jsonl"
    monkeypatch.setattr(node_events_module, "node_events_path", lambda: events_file)

    await emit_node("session-1", "thread-abc", "planner", "running")
    await emit_node("session-1", "thread-abc", "planner", "completed", output="x" * 600)
    # No thread id → not persisted (still broadcast-only).
    await emit_node("session-1", "", "planner", "running")

    lines = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2
    assert lines[0]["thread_id"] == "thread-abc"
    assert lines[0]["node"] == "planner"
    assert lines[1]["status"] == "completed"
    assert len(lines[1]["output"]) == 503  # 500 chars + "..."
