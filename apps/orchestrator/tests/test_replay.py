"""ASCII replay timeline formatting."""

from __future__ import annotations

from core.audit.replay import format_timeline
from core.bus.events import RUN_STARTED, TOOL_DENIED


def test_format_timeline_includes_events():
    rows = [
        {
            "seq": 1,
            "ts": "2026-07-12T10:00:00+00:00",
            "topic": RUN_STARTED,
            "session_id": "s1",
            "thread_id": "t1",
            "payload": {"type": "execution_started", "skill": "summarize_note"},
        },
        {
            "seq": 2,
            "ts": "2026-07-12T10:00:01+00:00",
            "topic": TOOL_DENIED,
            "session_id": "s1",
            "thread_id": "t1",
            "payload": {
                "type": "tool_denied",
                "tool": "shell.run",
                "skill": "summarize_note",
                "reason": "not_allowed",
                "arguments_sha256": "abc",
            },
        },
    ]
    text = format_timeline(rows, thread_id="t1")
    assert "correlation_id=t1" in text
    assert "session_start" in text
    assert "tool_called/denied" in text
    assert "shell.run" in text
    assert "2 event(s)" in text


def test_format_timeline_empty():
    assert "No audit events" in format_timeline([], thread_id="missing")
