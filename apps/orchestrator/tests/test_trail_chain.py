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


def test_forged_unchained_append_fails_verify(tmp_path: Path):
    """An unchained line after chained records is what a forged event looks
    like; readers would render it as real evidence, so verify must not call
    the trail OK."""
    trail = tmp_path / "audit-forward.jsonl"
    for i in range(3):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})
    forged = {"event_id": "FORGED", "action": {"type": "tool_called", "outcome": "success"}}
    with trail.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")

    result = verify_trail_file(trail)
    assert not result.ok
    assert "forged" in result.message.lower()
    assert result.first_bad_line == 4


def test_truncated_tail_with_sidecar_fails_verify(tmp_path: Path):
    """Cutting the newest lines off the file leaves a valid-looking chain; the
    sidecar remembers how far the writer actually got."""
    trail = tmp_path / "audit-forward.jsonl"
    for i in range(5):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})
    lines = trail.read_text(encoding="utf-8").strip().splitlines()
    trail.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")

    result = verify_trail_file(trail)
    assert not result.ok
    assert "truncated" in result.message.lower()


def test_missing_sidecar_verifies_with_a_truncation_caveat(tmp_path: Path):
    """A copied .jsonl without its sidecar is legitimate (verify on another
    machine), but the result must say tail deletion cannot be ruled out
    rather than imply a guarantee the file alone cannot carry."""
    from core.audit.trail_chain import chain_sidecar_path

    trail = tmp_path / "audit-forward.jsonl"
    for i in range(3):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})
    chain_sidecar_path(trail).unlink()

    result = verify_trail_file(trail)
    assert result.ok
    assert "cannot be ruled out" in result.message


def test_verify_reports_the_chain_head(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    for i in range(2):
        append_chained_line(trail, {"event_id": f"e{i}", "action": {"type": "tool_called"}})

    result = verify_trail_file(trail)
    assert result.ok
    assert result.head_seq == 2
    assert len(result.head_sha256) == 64


def test_sidecar_head_hash_mismatch_fails_verify(tmp_path: Path):
    from core.audit.trail_chain import chain_sidecar_path

    trail = tmp_path / "audit-forward.jsonl"
    append_chained_line(trail, {"event_id": "e0", "action": {"type": "tool_called"}})
    sidecar = chain_sidecar_path(trail)
    sidecar.write_text(json.dumps({"seq": 1, "last_sha256": "0" * 64}), encoding="utf-8")

    result = verify_trail_file(trail)
    assert not result.ok
    assert "sidecar head hash" in result.message.lower()


def test_compute_record_hash_stable():
    event = {"event_id": "1", "b": 2, "a": 1}
    h = compute_record_sha256(GENESIS_SHA256, event)
    assert len(h) == 64
    assert h == compute_record_sha256(GENESIS_SHA256, event)


def test_wrap_matches_compute():
    event = {"event_id": "z"}
    env = wrap_chained_record(1, GENESIS_SHA256, event)
    assert env["trail"]["record_sha256"] == compute_record_sha256(GENESIS_SHA256, event)
