"""Merkle tree over the hash-chained trail, for proofs that disclose one event.

The linear chain in trail_chain.py answers "has this file been altered". It
cannot answer "did this specific event happen" without handing over the entire
file, because every record's hash depends on the one before it. For an audit
that is the wrong shape: proving one tool call should not require disclosing a
month of unrelated work to whoever is asking.

A Merkle tree over the same `record_sha256` values answers it in O(log n)
hashes. Publish the root somewhere the audited machine cannot rewrite, and any
single event can later be proved against it while the rest of the trail stays
private.

**Additive by construction.** Nothing here changes the envelope, the canonical
event JSON, or `record_sha256`. Leaves are the record hashes the chain already
computes, so every trail ever written is compatible and no stored event needs
migrating. The root lives in the sidecar and is derived, never authoritative:
delete it and it recomputes from the file.

Deliberately not maintained on the append path. The root is what you publish
periodically, not per event, and `append_chained_line` is already the hottest
and least protected code in the system (it has no cross-process lock). Adding
an incremental tree update there would buy latency we do not need at a risk we
should not take.

## Why this is not the reference implementation it was modelled on

Microsoft's Agent Governance Toolkit ships a `MerkleAuditChain` doing the same
job, MIT licensed and readable. Two properties of that implementation are the
reason this one was written from RFC 6962 instead:

1. **No domain separation.** Leaves are hashed as the entry hash itself and
   internal nodes as `sha256(left || right)`, so the two are indistinguishable.
   That is the textbook Merkle second-preimage weakness: an internal node can be
   presented as a leaf, and a proof for a node that is not an event verifies
   against the root. RFC 6962 §2.1 prefixes leaves with 0x00 and internal nodes
   with 0x01 for exactly this reason, which is what this module does.

2. **Duplicated last node when a level is odd** (`right = left` where no sibling
   exists). That is the shape behind CVE-2012-2459: two different leaf sequences
   can produce the same root, so a proof can be valid for a tree that was never
   written. RFC 6962 splits at the largest power of two below `n` instead and
   never duplicates or pads, so distinct inputs always give distinct roots.

Neither is exotic and both are well documented; the point is only that a
tamper-evidence primitive is the wrong place to inherit a subtle weakness for
the sake of matching someone else's bytes. Interoperating on the *format* is
still worth doing, and a CT-style tree is the more interoperable choice anyway
since it is what Certificate Transparency, Trillian and Sigstore already speak.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentmetry.core.audit.trail_chain import chain_sidecar_path, is_chained_record

# RFC 6962 §2.1 domain separation. Without these two bytes a leaf and an
# internal node hash identically and the tree loses second-preimage resistance.
_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"

MERKLE_VERSION = 1


def _leaf_hash(record_sha256: str) -> bytes:
    return hashlib.sha256(_LEAF_PREFIX + bytes.fromhex(record_sha256)).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than n (RFC 6962's k).

    Splitting here rather than padding to a power of two is what keeps distinct
    leaf sequences mapping to distinct roots.
    """
    k = 1
    while k << 1 < n:
        k <<= 1
    return k


def _root(leaves: list[bytes]) -> bytes:
    if not leaves:
        # MTH({}) = SHA-256() of the empty string, per RFC 6962.
        return hashlib.sha256(b"").digest()
    if len(leaves) == 1:
        return leaves[0]
    k = _split(len(leaves))
    return _node_hash(_root(leaves[:k]), _root(leaves[k:]))


def _audit_path(index: int, leaves: list[bytes]) -> list[bytes]:
    if len(leaves) <= 1:
        return []
    k = _split(len(leaves))
    if index < k:
        return _audit_path(index, leaves[:k]) + [_root(leaves[k:])]
    return _audit_path(index - k, leaves[k:]) + [_root(leaves[:k])]


def _root_from_path(index: int, tree_size: int, leaf: bytes, path: list[bytes]) -> bytes:
    """Recompute the root from a leaf and its audit path (RFC 6962 §2.1.1).

    The index and tree size carry the shape, which is why a proof cannot be
    replayed against a differently sized tree.
    """
    if index >= tree_size:
        raise ValueError(f"leaf index {index} outside tree of size {tree_size}")
    fn, sn = index, tree_size - 1
    node = leaf
    for sibling in path:
        if fn & 1 or fn == sn:
            node = _node_hash(sibling, node)
            while fn & 1 == 0 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            node = _node_hash(node, sibling)
        fn >>= 1
        sn >>= 1
    if sn != 0:
        raise ValueError("audit path too short for the stated tree size")
    return node


# ----------------------------------------------------------------------
# Reading the trail
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TrailLeaves:
    """Record hashes in file order, with the seq each came from.

    Legacy unchained lines carry no `record_sha256` and are skipped rather than
    invented for. A trail that predates chaining simply has fewer leaves than
    lines, and `verify_trail_file` already reports that count separately.
    """

    record_hashes: list[str]
    seqs: list[int]
    skipped_legacy: int

    def __len__(self) -> int:
        return len(self.record_hashes)

    def index_of_seq(self, seq: int) -> int | None:
        try:
            return self.seqs.index(seq)
        except ValueError:
            return None


def read_leaves(trail_path: Path) -> TrailLeaves:
    hashes: list[str] = []
    seqs: list[int] = []
    skipped = 0
    if not trail_path.is_file():
        return TrailLeaves([], [], 0)
    with trail_path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not is_chained_record(record):
                skipped += 1
                continue
            trail = record["trail"]
            digest = str(trail.get("record_sha256") or "")
            if len(digest) != 64:
                skipped += 1
                continue
            hashes.append(digest)
            seqs.append(int(trail.get("seq") or 0))
    return TrailLeaves(hashes, seqs, skipped)


def merkle_root(trail_path: Path, tree_size: int | None = None) -> tuple[str, int]:
    """(root hex, tree size) for a trail file, optionally at a historical size.

    `tree_size` exists because the trail is append-only and live: the root
    changes on every event. A proof issued this morning names the tree it was
    issued against, and checking it against tonight's root fails for the most
    boring possible reason. Recomputing over the first `tree_size` leaves gives
    the root as it stood then, which is the thing the proof actually claims.

    Without this the whole feature is unusable on a running recorder, which is
    the only kind anybody has.
    """
    leaves = read_leaves(trail_path)
    hashes = leaves.record_hashes
    if tree_size is not None:
        if tree_size > len(hashes):
            raise ValueError(
                f"trail holds {len(hashes)} chained records, cannot reconstruct "
                f"a tree of size {tree_size}. The proof is either forged or from "
                "a different trail."
            )
        hashes = hashes[:tree_size]
    nodes = [_leaf_hash(h) for h in hashes]
    return _root(nodes).hex(), len(nodes)


# ----------------------------------------------------------------------
# Proofs
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class InclusionProof:
    seq: int
    leaf_index: int
    tree_size: int
    record_sha256: str
    path: list[str]
    root_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": MERKLE_VERSION,
            "alg": "rfc6962-sha256",
            "seq": self.seq,
            "leaf_index": self.leaf_index,
            "tree_size": self.tree_size,
            "record_sha256": self.record_sha256,
            "path": list(self.path),
            "root_sha256": self.root_sha256,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> InclusionProof:
        return InclusionProof(
            seq=int(data.get("seq") or 0),
            leaf_index=int(data["leaf_index"]),
            tree_size=int(data["tree_size"]),
            record_sha256=str(data["record_sha256"]),
            path=[str(p) for p in (data.get("path") or [])],
            root_sha256=str(data.get("root_sha256") or ""),
        )


def build_proof(trail_path: Path, seq: int) -> InclusionProof:
    leaves = read_leaves(trail_path)
    index = leaves.index_of_seq(seq)
    if index is None:
        raise ValueError(f"seq {seq} is not a chained record in {trail_path}")
    nodes = [_leaf_hash(h) for h in leaves.record_hashes]
    path = _audit_path(index, nodes)
    return InclusionProof(
        seq=seq,
        leaf_index=index,
        tree_size=len(nodes),
        record_sha256=leaves.record_hashes[index],
        path=[p.hex() for p in path],
        root_sha256=_root(nodes).hex(),
    )


def verify_proof(proof: InclusionProof, expected_root: str | None = None) -> tuple[bool, str]:
    """Check a proof, optionally against an independently held root.

    `expected_root` is the whole point. Verifying against the root carried
    inside the proof only shows the proof is internally consistent, which a
    forger can also arrange. The check that means something compares it to a
    root recorded somewhere the audited machine could not rewrite.
    """
    try:
        leaf = _leaf_hash(proof.record_sha256)
        path = [bytes.fromhex(p) for p in proof.path]
        computed = _root_from_path(proof.leaf_index, proof.tree_size, leaf, path).hex()
    except (ValueError, TypeError) as exc:
        return False, f"malformed proof: {exc}"

    if proof.root_sha256 and computed != proof.root_sha256:
        return False, (
            f"proof does not reconstruct its own root (computed {computed[:16]}…, "
            f"stated {proof.root_sha256[:16]}…)"
        )
    if expected_root:
        if computed != expected_root:
            return False, (
                f"proof is valid but for a different tree (computed {computed[:16]}…, "
                f"expected {expected_root[:16]}…)"
            )
        return True, f"verified against the supplied root {computed[:16]}…"
    return True, (
        f"internally consistent (root {computed[:16]}…). No external root was "
        "supplied, so this shows the proof is well formed, not that the trail "
        "was not rewritten."
    )


# ----------------------------------------------------------------------
# Sidecar
# ----------------------------------------------------------------------


def record_root(trail_path: Path) -> dict[str, Any]:
    """Recompute the root and store it alongside the chain head.

    Written as extra keys in the existing sidecar. `_load_sidecar` reads only
    `seq` and `last_sha256` and ignores everything else, so an older build reads
    a newer sidecar without noticing, which is the property that makes this
    additive rather than a format change.
    """
    root, size = merkle_root(trail_path)
    sidecar = chain_sidecar_path(trail_path)
    data: dict[str, Any] = {}
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["merkle_root"] = root
    data["merkle_tree_size"] = size
    data["merkle_alg"] = "rfc6962-sha256"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"root": root, "tree_size": size, "sidecar": str(sidecar)}
