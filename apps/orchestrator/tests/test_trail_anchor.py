"""Anchoring: the checkpoint that survives an attacker who owns the host.

The chain and the Merkle root are both computed from the file being checked, so
an attacker with write access to the data directory can edit an event, rebuild
every hash after it, rewrite the sidecar, and hand over a trail that verifies.
That is not hypothetical here -- `_rebuild_chain_around_edit` below does exactly
it in a dozen lines, and the first test asserts that the chain says OK
afterwards. Everything else in this file exists because of that test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmetry.core.audit import trail_anchor as a
from agentmetry.core.audit import trail_chain, trail_merkle


def _write_trail(path, n=8):
    for i in range(n):
        trail_chain.append_chained_line(path, {"seq_label": f"event-{i}", "tool": "read_file"})
    return path


def _rebuild_chain_around_edit(path, line_index, mutate):
    """Play the adversary: edit one event and re-chain everything after it.

    This is the whole threat model in one function. No exotic capability is
    required -- write access to the file and the ability to run sha256, which is
    to say, any process running as the user the recorder runs as.
    """
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mutate(records[line_index]["event"])
    prev = trail_chain.GENESIS_SHA256
    rebuilt = []
    for i, record in enumerate(records, start=1):
        envelope = trail_chain.wrap_chained_record(i, prev, record["event"])
        prev = envelope["trail"]["record_sha256"]
        rebuilt.append(json.dumps(envelope, separators=(",", ":")))
    path.write_text("\n".join(rebuilt) + "\n", encoding="utf-8")
    # ... and the sidecar, which is the part people forget is also just a file.
    sidecar = trail_chain.chain_sidecar_path(path)
    data = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    data["seq"] = len(rebuilt)
    data["last_sha256"] = prev
    sidecar.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------
# The gap being closed
# ----------------------------------------------------------------------


def test_chain_alone_cannot_see_a_rebuilt_trail(tmp_path):
    """The premise of issue #34. If this ever fails, anchoring is unnecessary."""
    trail = _write_trail(tmp_path / "t.jsonl")
    _rebuild_chain_around_edit(trail, 2, lambda e: e.update({"tool": "run_command"}))

    result = trail_chain.verify_trail_file(trail)
    assert result.ok, "the rebuild should be invisible to a self-contained check"


def test_an_anchor_sees_it(tmp_path):
    """Same edit, same rebuild, but a root was published beforehand."""
    trail = _write_trail(tmp_path / "t.jsonl")
    a.FileAnchorSink(a.anchor_path(trail)).publish(a.build_checkpoint(trail))

    _rebuild_chain_around_edit(trail, 2, lambda e: e.update({"tool": "run_command"}))

    coverage = a.verify_anchors(trail)
    assert not coverage.ok
    assert "altered" in coverage.failures[0].message


def test_deleting_records_below_a_checkpoint_is_reported_as_deletion(tmp_path):
    """Truncation and mutation are different incidents and must read differently.

    Both are tampering, but one means somebody edited history and the other
    means somebody removed it. A responder who cannot tell them apart from the
    output cannot scope the incident.
    """
    trail = _write_trail(tmp_path / "t.jsonl", n=8)
    a.FileAnchorSink(a.anchor_path(trail)).publish(a.build_checkpoint(trail))

    lines = trail.read_text(encoding="utf-8").splitlines()[:4]
    trail.write_text("\n".join(lines) + "\n", encoding="utf-8")

    coverage = a.verify_anchors(trail)
    assert not coverage.ok
    assert "deleted" in coverage.failures[0].message


# ----------------------------------------------------------------------
# Coverage is a range
# ----------------------------------------------------------------------


def test_records_appended_after_a_checkpoint_are_unanchored_not_failed(tmp_path):
    """A growing trail is the normal case, not an error.

    Scoring the tail as a failure would make the check cry wolf on every healthy
    recorder, and a check that is always red gets turned off.
    """
    trail = _write_trail(tmp_path / "t.jsonl", n=5)
    a.FileAnchorSink(a.anchor_path(trail)).publish(a.build_checkpoint(trail))
    _write_trail(trail, n=3)

    coverage = a.verify_anchors(trail)
    assert coverage.ok
    assert coverage.anchored_through == 5
    assert coverage.tree_size == 8
    assert coverage.unanchored == 3


def test_coverage_never_calls_an_unanchored_trail_anchored(tmp_path):
    """The wording is the feature; see `coverage_lines`."""
    trail = _write_trail(tmp_path / "t.jsonl", n=3)
    lines = " ".join(a.coverage_lines(a.verify_anchors(trail)))
    assert "anchors: none" in lines
    assert "rebuild" in lines


def test_local_anchor_log_admits_it_is_local(tmp_path):
    """The shipped sink is on the same disk as the thing it vouches for.

    Saying so in the output is the difference between an honest primitive and a
    checkbox, and it is the sentence a compliance reader needs to see.
    """
    trail = _write_trail(tmp_path / "t.jsonl", n=3)
    a.FileAnchorSink(a.anchor_path(trail)).publish(a.build_checkpoint(trail))
    lines = " ".join(a.coverage_lines(a.verify_anchors(trail)))
    assert "cannot write" in lines


# ----------------------------------------------------------------------
# The sink
# ----------------------------------------------------------------------


def test_sink_refuses_to_anchor_a_shrinking_tree(tmp_path):
    """Appending a smaller checkpoint would bury the evidence under a newer row."""
    trail = _write_trail(tmp_path / "t.jsonl", n=6)
    sink = a.FileAnchorSink(a.anchor_path(trail))
    sink.publish(a.build_checkpoint(trail))

    shrunk = a.Checkpoint(
        tree_size=3, root_sha256="0" * 64, head_seq=3, head_sha256="1" * 64,
        timestamp="2026-01-01T00:00:00Z", host_id="h", trail_name=trail.name,
    )
    with pytest.raises(ValueError, match="lost records"):
        sink.publish(shrunk)


def test_sink_appends_and_never_rewrites(tmp_path):
    trail = _write_trail(tmp_path / "t.jsonl", n=4)
    sink = a.FileAnchorSink(a.anchor_path(trail))
    sink.publish(a.build_checkpoint(trail))
    _write_trail(trail, n=2)
    receipt = sink.publish(a.build_checkpoint(trail))

    checkpoints = a.read_checkpoints(a.anchor_path(trail))
    assert [c.tree_size for c in checkpoints] == [4, 6]
    assert receipt.ref.endswith(":2")
    assert receipt.detail["local"] is True


def test_file_sink_satisfies_the_protocol():
    """The seam is the point: an operator's own sink must be substitutable."""
    assert isinstance(a.FileAnchorSink(Path("x")), a.AnchorSink)


def test_checkpoint_for_a_different_trail_is_not_counted(tmp_path):
    """Two trails on one host must not vouch for each other."""
    trail = _write_trail(tmp_path / "t.jsonl", n=4)
    other = a.build_checkpoint(trail)
    foreign = a.Checkpoint(**{**other.__dict__, "trail_name": "somebody-elses.jsonl"})
    anchors = a.anchor_path(trail)
    anchors.write_text(json.dumps(foreign.to_dict()) + "\n", encoding="utf-8")

    coverage = a.verify_anchors(trail)
    assert not coverage.ok
    assert coverage.anchored_through == 0


# ----------------------------------------------------------------------
# Shape
# ----------------------------------------------------------------------


def test_checkpoint_round_trips(tmp_path):
    trail = _write_trail(tmp_path / "t.jsonl", n=4)
    cp = a.build_checkpoint(trail)
    assert a.Checkpoint.from_dict(cp.to_dict()) == cp


def test_checkpoint_commits_to_the_merkle_root(tmp_path):
    trail = _write_trail(tmp_path / "t.jsonl", n=7)
    cp = a.build_checkpoint(trail)
    root, size = trail_merkle.merkle_root(trail)
    assert (cp.root_sha256, cp.tree_size) == (root, size)


def test_statement_carries_everything_needed_to_check_it_by_hand(tmp_path):
    """A commitment nobody can interpret in five years is not a commitment."""
    trail = _write_trail(tmp_path / "t.jsonl", n=4)
    line = a.build_checkpoint(trail).statement()
    for token in ("agentmetry-anchor", "rfc6962-sha256", "tree_size=4", "root=", "head_seq="):
        assert token in line


def test_anchoring_an_empty_trail_is_refused(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no chained records"):
        a.build_checkpoint(empty)


def test_malformed_checkpoint_lines_are_skipped_not_trusted(tmp_path):
    trail = _write_trail(tmp_path / "t.jsonl", n=4)
    anchors = a.anchor_path(trail)
    anchors.write_text("not json\n" + json.dumps({"tree_size": "x"}) + "\n", encoding="utf-8")
    assert a.read_checkpoints(anchors) == []
    assert a.verify_anchors(trail).anchored_through == 0
