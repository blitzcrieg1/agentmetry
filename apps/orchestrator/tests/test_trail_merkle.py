"""Merkle tree over the trail: proofs that disclose one event, not the file.

The two properties that matter here are the ones the reference implementation
this was modelled on does not have, so they are tested directly rather than
assumed: leaves and internal nodes must be distinguishable, and distinct leaf
sequences must produce distinct roots.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from agentmetry.core.audit import trail_chain, trail_merkle as m


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


# ----------------------------------------------------------------------
# Tree construction
# ----------------------------------------------------------------------


@pytest.mark.parametrize("n", list(range(1, 34)))
def test_every_leaf_proves_against_the_root(n):
    """Exhaustive for small trees, because an off-by-one in the split shows up
    only at particular sizes and a spot check would miss it."""
    leaves = [m._leaf_hash(_digest(f"leaf-{i}")) for i in range(n)]
    root = m._root(leaves)
    for i in range(n):
        path = m._audit_path(i, leaves)
        assert m._root_from_path(i, n, leaves[i], path) == root, f"n={n} i={i}"


def test_leaves_and_internal_nodes_are_domain_separated():
    """RFC 6962 §2.1 prefixes leaves with 0x00 and internal nodes with 0x01.

    Without this an internal node hashes identically to a leaf, and a proof can
    be produced for a node that is not an event at all. The toolkit this was
    modelled on hashes both as bare SHA-256, which is the textbook Merkle
    second-preimage weakness.
    """
    assert m._LEAF_PREFIX != m._NODE_PREFIX
    a, b = m._leaf_hash(_digest("a")), m._leaf_hash(_digest("b"))
    internal = m._node_hash(a, b)
    assert internal not in (a, b)
    # An internal node reinterpreted as leaf material must not collide either.
    assert m._leaf_hash(internal.hex()) != internal


def test_distinct_leaf_sequences_give_distinct_roots():
    """The CVE-2012-2459 shape: duplicating the final leaf to fill an odd level
    lets two different logs share a root. RFC 6962 splits instead of padding."""
    three = [m._leaf_hash(_digest(f"l{i}")) for i in range(3)]
    three_plus_dup = three + [m._leaf_hash(_digest("l2"))]
    assert m._root(three) != m._root(three_plus_dup)

    # Nor may a prefix collide with the whole.
    assert m._root(three[:2]) != m._root(three)


def test_empty_tree_is_defined():
    assert m._root([]) == hashlib.sha256(b"").digest()


def test_proof_length_is_logarithmic():
    leaves = [m._leaf_hash(_digest(f"l{i}")) for i in range(1000)]
    assert len(m._audit_path(500, leaves)) <= 10 + 1


# ----------------------------------------------------------------------
# Against a real trail file
# ----------------------------------------------------------------------


@pytest.fixture()
def trail(tmp_path):
    path = tmp_path / "trail.jsonl"
    for i in range(9):
        trail_chain.append_chained_line(path, {"event_id": f"e{i}", "n": i})
    return path


def test_root_covers_every_chained_record(trail):
    leaves = m.read_leaves(trail)
    assert len(leaves) == 9
    assert leaves.skipped_legacy == 0
    root, size = m.merkle_root(trail)
    assert size == 9
    assert len(root) == 64


def test_a_single_event_proves_without_the_rest(trail):
    """The whole point. The chain can only say the file is intact; this says one
    event is in it, in O(log n) hashes and disclosing nothing else."""
    root, _ = m.merkle_root(trail)
    proof = m.build_proof(trail, seq=5)
    ok, message = m.verify_proof(proof, expected_root=root)
    assert ok, message
    assert len(proof.path) <= 4
    # Nothing about the other events travels with the proof.
    payload = json.dumps(proof.to_dict())
    for i in range(9):
        assert f'"e{i}"' not in payload


def test_a_tampered_leaf_fails(trail):
    proof = m.build_proof(trail, seq=5)
    forged = m.InclusionProof.from_dict({**proof.to_dict(), "record_sha256": "f" * 64})
    ok, message = m.verify_proof(forged)
    assert not ok
    assert "does not reconstruct" in message


def test_a_tampered_path_fails(trail):
    proof = m.build_proof(trail, seq=5)
    forged = m.InclusionProof.from_dict(
        {**proof.to_dict(), "path": ["0" * 64] + proof.path[1:]}
    )
    assert not m.verify_proof(forged)[0]


def test_a_valid_proof_for_another_tree_is_rejected(trail):
    """Verifying against a root you already hold is the check that means
    something. Without it a forger supplies both the proof and the root it
    matches, and the arithmetic is perfectly consistent."""
    proof = m.build_proof(trail, seq=5)
    ok, message = m.verify_proof(proof, expected_root="a" * 64)
    assert not ok
    assert "different tree" in message


def test_verifying_without_an_external_root_says_so(trail):
    """A proof checked only against itself proves well-formedness, not custody.
    The message has to admit that or it is worse than no message."""
    proof = m.build_proof(trail, seq=5)
    ok, message = m.verify_proof(proof)
    assert ok
    assert "not that the trail was not rewritten" in message


def test_leaf_index_outside_the_tree_is_rejected(trail):
    proof = m.build_proof(trail, seq=5)
    forged = m.InclusionProof.from_dict({**proof.to_dict(), "leaf_index": 99})
    ok, message = m.verify_proof(forged)
    assert not ok
    assert "outside tree" in message


def test_unknown_seq_raises(trail):
    with pytest.raises(ValueError, match="not a chained record"):
        m.build_proof(trail, seq=999)


def test_legacy_unchained_lines_are_skipped_not_invented_for(trail):
    """Trails predating the chain have plain event lines with no record hash.
    Counting them as leaves would put a hash in the tree that nothing produced."""
    with trail.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event_id": "legacy", "no": "envelope"}) + "\n")
    leaves = m.read_leaves(trail)
    assert len(leaves) == 9
    assert leaves.skipped_legacy == 1


def test_a_missing_trail_is_empty_rather_than_an_error(tmp_path):
    root, size = m.merkle_root(tmp_path / "absent.jsonl")
    assert size == 0
    assert root == hashlib.sha256(b"").hexdigest()


def test_a_proof_survives_the_trail_growing_underneath_it(trail):
    """The bug that made this feature useless, found by running it rather than
    reading it.

    The trail is append-only and live. A proof issued at 09:00 names the tree it
    was issued against; by the time anyone checks it the recorder has appended
    more events and the current root is different. Comparing against the current
    root fails for the most boring reason available, and the first end-to-end
    run of the CLI did exactly that.
    """
    proof = m.build_proof(trail, seq=5)
    root_then, size_then = m.merkle_root(trail)

    for i in range(20):
        trail_chain.append_chained_line(trail, {"event_id": f"later-{i}"})

    root_now, size_now = m.merkle_root(trail)
    assert root_now != root_then and size_now > size_then

    historical, size = m.merkle_root(trail, tree_size=proof.tree_size)
    assert size == size_then
    assert historical == root_then

    ok, message = m.verify_proof(proof, expected_root=historical)
    assert ok, message
    assert not m.verify_proof(proof, expected_root=root_now)[0]


def test_a_tree_size_larger_than_the_trail_is_refused(trail):
    """A proof claiming more records than exist is forged or from elsewhere.
    Truncating silently would let it verify against a prefix."""
    with pytest.raises(ValueError, match="cannot reconstruct"):
        m.merkle_root(trail, tree_size=10_000)


# ----------------------------------------------------------------------
# Additive, not a format change
# ----------------------------------------------------------------------


def test_the_root_is_derived_and_never_authoritative(trail):
    """Delete the sidecar and it recomputes. Anything that cannot be rebuilt
    from the trail would make the sidecar a second source of truth."""
    before, _ = m.merkle_root(trail)
    trail_chain.chain_sidecar_path(trail).unlink()
    after, _ = m.merkle_root(trail)
    assert before == after


def test_recording_the_root_leaves_the_chain_head_readable(trail):
    """The sidecar gains keys; it does not change shape.

    An older build reads `seq` and `last_sha256` and ignores the rest, which is
    what makes this additive. The red line here is real: every stored event and
    every SIEM adapter reads the current envelope, so a format swap would strand
    trails people already have.
    """
    head_before = trail_chain.load_chain_head(trail)
    result = m.record_root(trail)

    head_after = trail_chain.load_chain_head(trail)
    assert head_after.seq == head_before.seq
    assert head_after.last_sha256 == head_before.last_sha256

    data = json.loads(trail_chain.chain_sidecar_path(trail).read_text(encoding="utf-8"))
    assert data["merkle_root"] == result["root"]
    assert data["merkle_alg"] == "rfc6962-sha256"
    assert "seq" in data and "last_sha256" in data


def test_record_sha256_is_untouched_by_any_of_this(trail):
    """Leaves are the hashes the chain already computes. If this test ever
    fails, the change stopped being additive."""
    lines = [
        json.loads(line)
        for line in trail.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for record in lines:
        event = record["event"]
        expected = trail_chain.compute_record_sha256(record["trail"]["prev_sha256"], event)
        assert record["trail"]["record_sha256"] == expected

    leaves = m.read_leaves(trail)
    assert leaves.record_hashes == [r["trail"]["record_sha256"] for r in lines]


def test_the_chain_still_verifies_after_recording_a_root(trail):
    m.record_root(trail)
    result = trail_chain.verify_trail_file(trail)
    assert result.ok, result.message
