"""Tamper-evident hash chain for audit JSONL trails."""

from __future__ import annotations

import json
from pathlib import Path

from core.audit.trail_chain import (
    GENESIS_SHA256,
    append_chained_line,
    compute_record_sha256,
    unwrap_trail_record,
    verify_trail_file,
    wrap_chained_record,
)


def test_wrap_and_verify_chain(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    e1 = {"event_id": "a1", "action": {"type": "tool_called", "outcome": "success"}}
    e2 = {"event_id": "a2", "action": {"type": "tool_called", "outcome": "success"}}

    append_chained_line(trail, e1)
    append_chained_line(trail, e2)

    result = verify_trail_file(trail)
    assert result.ok
    assert result.lines_chained == 2
    assert result.lines_legacy == 0

    lines = trail.read_text(encoding="utf-8").strip().splitlines()
    r0 = json.loads(lines[0])
    assert r0["trail"]["seq"] == 1
    assert r0["trail"]["prev_sha256"] == GENESIS_SHA256
    assert unwrap_trail_record(r0)["event_id"] == "a1"


def test_tamper_fails_verify(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    append_chained_line(trail, {"event_id": "x", "action": {"type": "session_start"}})

    text = trail.read_text(encoding="utf-8")
    tampered = text.replace('"session_start"', '"session_end"')
    trail.write_text(tampered, encoding="utf-8")

    result = verify_trail_file(trail)
    assert not result.ok
    assert "mismatch" in result.message.lower()


def test_legacy_prefix_still_verifies_chained_suffix(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    legacy = {"event_id": "old", "action": {"type": "tool_called"}}
    trail.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    append_chained_line(trail, {"event_id": "new", "action": {"type": "tool_called"}})

    result = verify_trail_file(trail)
    assert result.ok
    assert result.lines_legacy == 1
    assert result.lines_chained == 1


def test_compute_record_hash_stable():
    event = {"event_id": "1", "b": 2, "a": 1}
    h = compute_record_sha256(GENESIS_SHA256, event)
    assert len(h) == 64
    assert h == compute_record_sha256(GENESIS_SHA256, event)


def test_wrap_matches_compute():
    event = {"event_id": "z"}
    env = wrap_chained_record(1, GENESIS_SHA256, event)
    assert env["trail"]["record_sha256"] == compute_record_sha256(GENESIS_SHA256, event)
