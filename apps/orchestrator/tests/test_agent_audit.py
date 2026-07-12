"""Tests for AgentAudit canonical normalization and JSONL export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.audit.canonical import SCHEMA_VERSION, normalize_outbox_row
from core.audit.sinks import FileAuditSink
from core.bus.audit_exporter import event_to_outbox_row
from core.bus.events import (
    RUN_APPROVAL_DENIED,
    RUN_APPROVAL_GRANTED,
    RUN_STARTED,
    TOOL_CALLED,
    TOOL_DENIED,
    Event,
)
from core.bus.outbox import EventOutbox


def test_normalize_tool_called():
    row = {
        "seq": 5,
        "ts": "2026-07-12T10:00:00+00:00",
        "topic": TOOL_CALLED,
        "session_id": "sess-1",
        "thread_id": "thread-abc",
        "payload": {
            "type": "tool_called",
            "tool": "vault_fs.read_file",
            "skill": "summarize_note",
            "arguments_sha256": "abc123",
        },
    }
    out = normalize_outbox_row(row)
    assert out is not None
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["correlation_id"] == "thread-abc"
    assert out["action"] == {"type": "tool_called", "outcome": "success", "reason": ""}
    assert out["tool"]["qualified"] == "vault_fs.read_file"
    assert out["tool"]["server"] == "vault_fs"
    assert out["tool"]["input_hash"] == "abc123"


def test_normalize_tool_denied():
    row = {
        "seq": 6,
        "ts": "2026-07-12T10:00:01+00:00",
        "topic": TOOL_DENIED,
        "session_id": "sess-1",
        "thread_id": "thread-abc",
        "payload": {
            "type": "tool_denied",
            "tool": "shell.run",
            "skill": "weekly_review",
            "reason": "not_allowed",
            "arguments_sha256": "deadbeef",
        },
    }
    out = normalize_outbox_row(row)
    assert out is not None
    assert out["action"]["outcome"] == "denied"
    assert out["action"]["reason"] == "not_allowed"


def test_normalize_approval_granted():
    row = {
        "seq": 7,
        "ts": "2026-07-12T10:00:02+00:00",
        "topic": RUN_APPROVAL_GRANTED,
        "session_id": "sess-1",
        "thread_id": "thread-abc",
        "payload": {
            "type": "approval_granted",
            "skill": "customer_reply",
            "edited": True,
        },
    }
    out = normalize_outbox_row(row)
    assert out["action"]["type"] == "approval_response"
    assert out["action"]["outcome"] == "success"
    assert out["action"]["reason"] == "approved_with_edit"


def test_normalize_skips_unknown_topic():
    row = {
        "seq": 1,
        "ts": "2026-07-12T10:00:00+00:00",
        "topic": "llm/token",
        "session_id": "",
        "thread_id": "",
        "payload": {},
    }
    assert normalize_outbox_row(row) is None


async def test_jsonl_append(tmp_path: Path):
    path = tmp_path / "audit-forward.jsonl"
    sink = FileAuditSink(path)
    row = {
        "seq": 1,
        "ts": "2026-07-12T10:00:00+00:00",
        "topic": RUN_STARTED,
        "session_id": "s1",
        "thread_id": "t1",
        "payload": {"type": "execution_started", "skill": "summarize_note"},
    }
    canonical = normalize_outbox_row(row)
    assert canonical is not None
    await sink.emit(canonical)
    await sink.emit(canonical)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["action"]["type"] == "session_start"
    assert parsed["agent"]["skill_id"] == "summarize_note"


def test_outbox_read_by_thread_id(tmp_path: Path):
    outbox = EventOutbox(tmp_path / "events.db")
    outbox.append(Event(topic=RUN_STARTED, payload={"skill": "a"}, seq=1, thread_id="t1"))
    outbox.append(Event(topic=TOOL_CALLED, payload={"tool": "x.y"}, seq=2, thread_id="t1"))
    outbox.append(Event(topic=RUN_STARTED, payload={"skill": "b"}, seq=3, thread_id="t2"))

    rows = outbox.read_by_thread_id("t1")
    assert len(rows) == 2
    assert [r["seq"] for r in rows] == [1, 2]


def test_event_to_outbox_row():
    ev = Event(
        topic=RUN_APPROVAL_DENIED,
        payload={"type": "approval_denied", "skill": "x"},
        seq=99,
        thread_id="t9",
        session_id="s9",
        ts="2026-07-12T11:00:00+00:00",
    )
    row = event_to_outbox_row(ev)
    assert row["topic"] == RUN_APPROVAL_DENIED
    assert row["seq"] == 99
