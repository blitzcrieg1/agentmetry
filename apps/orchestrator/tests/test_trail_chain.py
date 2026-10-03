"""Tamper-evident hash chain for audit JSONL trails."""

from __future__ import annotations

import json
from pathlib import Path

from agentmetry.core.audit.trail_chain import (
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
    from agentmetry.core.audit.trail_chain import chain_sidecar_path

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
    from agentmetry.core.audit.trail_chain import chain_sidecar_path

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


# --- rotation (pilot hardening item 20, #101) --------------------------------
#
# The trail was one unbounded file. Rotation archives the active file whole
# and the chain carries on in a new one. Every reader walks the segments, so
# verification, Merkle roots and the forwarder see one continuous trail.

import pytest  # noqa: E402

from agentmetry.core.audit import trail_rotation  # noqa: E402


def _ev(n: int) -> dict:
    return {"event_id": f"r{n}", "correlation_id": "s", "action": {"type": "tool_called", "outcome": "success"}}


def _fill(trail: Path, count: int, start: int = 0, rotate_bytes: int = 0) -> None:
    for n in range(start, start + count):
        append_chained_line(trail, _ev(n), rotate_bytes=rotate_bytes)


def test_rotation_by_size_keeps_one_verifiable_chain(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 30, rotate_bytes=1500)
    archived = trail_rotation.archived(trail)
    assert len(archived) >= 2, "a 1500-byte threshold must have rotated more than once"
    result = verify_trail_file(trail)
    assert result.ok, result.message
    assert result.lines_chained == 30
    assert result.head_seq == 30


def test_the_chain_crosses_the_segment_boundary(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 3)
    segment = trail_rotation.rotate(trail)
    _fill(trail, 1, start=3)
    last_archived = json.loads(segment.read_text(encoding="utf-8").splitlines()[-1])["trail"]
    first_active = json.loads(trail.read_text(encoding="utf-8").splitlines()[0])["trail"]
    assert first_active["seq"] == last_archived["seq"] + 1
    assert first_active["prev_sha256"] == last_archived["record_sha256"]


def test_segments_are_named_by_their_seq_range(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 5)
    segment = trail_rotation.rotate(trail)
    assert segment.name == "audit-forward.000000000001-000000000005.jsonl"
    assert segment.parent.name == "audit-forward.archive"
    entry = trail_rotation.manifest(trail)[0]
    assert (entry["first_seq"], entry["last_seq"]) == (1, 5)
    assert len(entry["file_sha256"]) == 64
    assert not trail.exists(), "the active file is moved whole, not copied"


def test_tampering_in_an_archived_segment_is_caught_and_named(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 4)
    segment = trail_rotation.rotate(trail)
    _fill(trail, 2, start=4)
    lines = segment.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["event"]["event_id"] = "forged"
    lines[1] = json.dumps(record)
    segment.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = verify_trail_file(trail)
    assert not result.ok
    assert segment.name in result.message
    assert result.first_bad_line == 2, "line numbers stay numeric for callers"


def test_deleting_an_archived_segment_breaks_verification(tmp_path: Path):
    """No silent retention: removing old evidence must be visible."""
    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 3)
    segment = trail_rotation.rotate(trail)
    _fill(trail, 3, start=3)
    segment.unlink()
    assert not verify_trail_file(trail).ok


def test_a_lost_sidecar_after_rotation_does_not_fork_the_chain(tmp_path: Path):
    from agentmetry.core.audit.trail_chain import chain_sidecar_path

    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 3)
    trail_rotation.rotate(trail)
    chain_sidecar_path(trail).unlink()
    head = append_chained_line(trail, _ev(3))
    assert head.seq == 4, "restarting at seq 1 would fork the chain"
    assert verify_trail_file(trail).ok


def test_rotation_does_not_change_the_merkle_root(tmp_path: Path):
    """An anchor published before a rotation must still verify after it."""
    from agentmetry.core.audit.trail_merkle import build_proof, merkle_root, verify_proof

    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 9)
    before = merkle_root(trail)
    proof = build_proof(trail, 4)
    trail_rotation.rotate(trail)
    assert merkle_root(trail) == before
    _fill(trail, 2, start=9)
    assert merkle_root(trail, tree_size=before[1])[0] == before[0]
    assert verify_proof(proof, expected_root=before[0])[0]


def test_the_index_backfill_reads_archived_segments(tmp_path: Path, monkeypatch):
    from agentmetry.core.audit import migrate
    from agentmetry.core.config import settings

    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 4)
    trail_rotation.rotate(trail)
    _fill(trail, 2, start=4)
    monkeypatch.setattr(settings, "audit_export_path", trail)
    inserted: list[dict] = []

    class _Db:
        def insert_batch(self, batch):
            inserted.extend(batch)
            return len(batch)

    monkeypatch.setattr(migrate, "get_trail_db", lambda: _Db())
    assert migrate.backfill_db_from_jsonl() == 6
    assert [e["event_id"] for e in inserted] == [f"r{n}" for n in range(6)]


async def test_the_forwarder_follows_its_cursor_into_the_next_segment(tmp_path: Path):
    import httpx

    from agentmetry.core.audit import forwarder as fw

    trail = tmp_path / "audit-forward.jsonl"
    received: list[str] = []

    class _Siem:
        name = "probe"
        max_batch = 100

        def make_client(self):
            return httpx.AsyncClient()

        async def send_batch(self, client, events):
            received.extend(e["event_id"] for e in events)

    async def _sleep(_s):
        return None

    forwarder = fw.Forwarder(_Siem(), trail, sleep=_sleep)
    _fill(trail, 3)
    async with httpx.AsyncClient() as client:
        await forwarder.step(client)
        _fill(trail, 2, start=3)  # appended after the last forward, before the rotation
        trail_rotation.rotate(trail)
        _fill(trail, 2, start=5)
        for _ in range(4):
            await forwarder.step(client)
    assert received == [f"r{n}" for n in range(7)]


def test_rotate_refuses_to_overwrite_a_segment(tmp_path: Path):
    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 2)
    segment = trail_rotation.rotate(trail)
    trail.write_text(segment.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(FileExistsError):
        trail_rotation.rotate(trail)


def test_an_empty_trail_does_not_rotate(tmp_path: Path):
    assert trail_rotation.rotate(tmp_path / "audit-forward.jsonl") is None


def test_the_cli_rotates_lists_and_verifies(tmp_path: Path, capsys):
    from agentmetry.cli import main

    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 3)
    assert main(["trail", "rotate", "--path", str(trail)]) == 0
    assert main(["trail", "segments", "--path", str(trail)]) == 0
    out = capsys.readouterr().out
    assert "seq 1-3" in out and "not created yet" in out
    assert main(["verify", "--trail", str(trail)]) == 0, "only archived segments, still a trail"


def test_the_dogfood_chain_check_sees_a_rotated_trail(tmp_path: Path, monkeypatch):
    from agentmetry.core.audit import dogfood
    from agentmetry.core.config import settings

    trail = tmp_path / "audit-forward.jsonl"
    _fill(trail, 3)
    trail_rotation.rotate(trail)
    monkeypatch.setattr(settings, "audit_export_path", trail)
    report = dogfood.DogfoodReport.__new__(dogfood.DogfoodReport)
    dogfood._attach_health(report)
    assert report.chain_ok is True
