"""Periodic checkpoints committing the trail to somewhere the host cannot rewrite.

`trail_chain.py` chains every record and `trail_merkle.py` builds a root over
those chains. Both are computed *on the audited machine, from the audited file*.
Against accidental corruption, truncation, and a naive edit that is enough. It
is not enough against the threat model this tool claims to serve.

An attacker with write access to the data directory can edit an event, recompute
every subsequent `record_sha256`, rewrite the `.chain` sidecar head, and hand you
a trail that verifies perfectly. Every input to the verification lives inside the
blast radius. That is not a bug in the chain, it is the ceiling of what any
self-contained file can prove, and calling the result "tamper-evident" without
saying so overstates it to exactly the reader least able to check.

An anchor raises the ceiling. Publish `(tree_size, root_sha256)` somewhere the
local attacker does not control, and any later edit to a record below that tree
size changes the root and no longer matches what was published. The trail stays
local; only a 32-byte commitment leaves. Nothing about the events is disclosed by
the root, which is what makes this safe to publish at all.

## What the shipped sink does and does not buy you

`FileAnchorSink` appends checkpoints to a local JSONL file. On its own, on the
same disk, it adds nearly nothing: an attacker who can rewrite the trail can
rewrite the anchor file beside it. It is shipped because it makes the interface
real, and because the file becomes worth something the moment it leaves the host
by any means the attacker does not mediate. Committing it to a git repo with a
remote, syncing it to a bucket with object-lock, or mailing it to yourself all
qualify. `verify_anchors` says which situation you are in rather than implying
the stronger one.

The interesting sinks are the ones this repo deliberately does not implement:
an RFC 3161 timestamp authority, a transparency log, an internal append-only
store. Those involve a third party, and picking one for the operator would be
choosing their trust anchor for them. `AnchorSink` is the seam; `docs/anchoring.md`
documents how to attach one with tools an operator already has.

## Anchored is a range, not a boolean

A checkpoint covers the first `tree_size` records and says nothing about what was
appended after it. Reporting "anchored" for the whole trail because one
checkpoint exists would be its own kind of dishonesty, so coverage is reported as
a range and the tail is named as what it is: chain-verified, not anchored.
"""

from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from agentmetry.core.audit.trail_merkle import merkle_root, read_leaves

ANCHOR_VERSION = 1
ANCHOR_ALG = "rfc6962-sha256"


def anchor_path(trail_path: Path) -> Path:
    """Default anchor log for a trail: `<trail>.anchors.jsonl`.

    Deliberately a sibling rather than a key inside the `.chain` sidecar. The
    sidecar is rewritten in place on every append; an anchor log must only ever
    grow, and putting an append-only record inside a file whose whole job is to
    be overwritten is how append-only records quietly stop being append-only.
    """
    return trail_path.with_name(trail_path.name + ".anchors.jsonl")


def resolve_anchor_log(
    trail_path: Path, explicit: str | Path | None = None
) -> tuple[Path, str]:
    """Which anchor log to use, and where that choice came from.

    Precedence: an explicit `--anchors`, then `AGENTMETRY_ANCHOR_LOG`, then the
    sibling default. The source is returned because the caller needs it to say
    anything honest: only for the sibling default do we *know* the log sits
    beside the trail and is therefore rewritable by whoever rewrote it. A
    configured path might be a working copy of a protected remote or might be a
    second file on the same disk, and this process cannot tell which, so it
    should not claim either.

    Deliberately not folded into `verify_anchors`. That function decides whether
    an audit trail was tampered with, and giving it a hidden dependency on
    ambient configuration means a test and a production run can check different
    files while reading identically.
    """
    if explicit:
        return Path(explicit), "flag"
    try:
        from agentmetry.core.config import settings

        configured = str(getattr(settings, "anchor_log_path", "") or "").strip()
        if configured:
            return Path(configured), "config"
    except Exception:
        pass
    return anchor_path(Path(trail_path)), "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_host_id() -> str:
    """Operator id if configured, else the machine name.

    Matches how the rest of the pipeline attributes events (`settings.operator_id`
    falling back to the host), so a checkpoint and the events it commits to carry
    the same identity.
    """
    try:
        from agentmetry.core.config import settings

        configured = str(getattr(settings, "operator_id", "") or "").strip()
        if configured:
            return configured
    except Exception:
        pass
    return platform.node() or "unknown-host"


# ----------------------------------------------------------------------
# The commitment
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Checkpoint:
    """A signed-off-on statement: at this size, the trail hashed to this root.

    `head_sha256` is carried alongside the root because the two fail differently.
    The root detects any edit to a record below `tree_size`. The chain head also
    binds the order the records were *written* in. Recording both costs 32 bytes
    and means a checkpoint stays meaningful even if one construction is later
    found wanting.
    """

    tree_size: int
    root_sha256: str
    head_seq: int
    head_sha256: str
    timestamp: str
    host_id: str
    trail_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": ANCHOR_VERSION,
            "alg": ANCHOR_ALG,
            "tree_size": self.tree_size,
            "root_sha256": self.root_sha256,
            "head_seq": self.head_seq,
            "head_sha256": self.head_sha256,
            "timestamp": self.timestamp,
            "host_id": self.host_id,
            "trail_name": self.trail_name,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Checkpoint:
        return Checkpoint(
            tree_size=int(data["tree_size"]),
            root_sha256=str(data["root_sha256"]),
            head_seq=int(data.get("head_seq") or 0),
            head_sha256=str(data.get("head_sha256") or ""),
            timestamp=str(data.get("timestamp") or ""),
            host_id=str(data.get("host_id") or ""),
            trail_name=str(data.get("trail_name") or ""),
        )

    def statement(self) -> str:
        """The one line to publish when the sink takes text, not JSON.

        Stable, sorted, and self-describing so that a TSA receipt or a git commit
        message can be checked by hand years later without this code.
        """
        return (
            f"agentmetry-anchor v{ANCHOR_VERSION} alg={ANCHOR_ALG} "
            f"trail={self.trail_name} tree_size={self.tree_size} "
            f"root={self.root_sha256} head_seq={self.head_seq} "
            f"head={self.head_sha256} host={self.host_id} at={self.timestamp}"
        )


def build_checkpoint(trail_path: Path, host_id: str = "") -> Checkpoint:
    """Commit to the trail as it stands right now."""
    root, size = merkle_root(trail_path)
    if not size:
        raise ValueError(f"{trail_path} holds no chained records to anchor")
    leaves = read_leaves(trail_path)
    return Checkpoint(
        tree_size=size,
        root_sha256=root,
        head_seq=leaves.seqs[-1] if leaves.seqs else 0,
        head_sha256=leaves.record_hashes[-1] if leaves.record_hashes else "",
        timestamp=_now(),
        host_id=host_id or default_host_id(),
        trail_name=trail_path.name,
    )


# ----------------------------------------------------------------------
# Sinks
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class AnchorReceipt:
    """What a sink hands back: where the commitment went, and how to find it.

    `ref` is opaque on purpose. A file sink returns a line number, a timestamp
    authority returns a serial, a transparency log returns an index. Verification
    of the receipt itself belongs to whoever operates the sink, which is the
    entire reason the sink is not us.
    """

    sink: str
    ref: str
    published_at: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sink": self.sink,
            "ref": self.ref,
            "published_at": self.published_at,
            "detail": dict(self.detail),
        }


@runtime_checkable
class AnchorSink(Protocol):
    """Somewhere a checkpoint can be published.

    One method, and it takes the whole checkpoint rather than just the root. A
    sink that records only the root cannot tell you which trail or how much of it
    was covered, and a commitment you cannot locate afterwards is not a
    commitment.
    """

    name: str

    def publish(self, checkpoint: Checkpoint) -> AnchorReceipt: ...


class FileAnchorSink:
    """Append-only local JSONL. Proves the interface; see the module docstring.

    Fails loudly rather than silently on a shrinking tree: a checkpoint whose
    `tree_size` is below one already recorded means the trail lost records, and
    quietly appending it would bury the single most alarming thing this file can
    observe.
    """

    name = "file"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def publish(self, checkpoint: Checkpoint) -> AnchorReceipt:
        existing = read_checkpoints(self.path)
        for prior in existing:
            if checkpoint.tree_size < prior.tree_size:
                raise ValueError(
                    f"refusing to anchor tree size {checkpoint.tree_size}: "
                    f"a checkpoint at {prior.tree_size} was already recorded "
                    f"({prior.timestamp}). The trail has lost records."
                )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(checkpoint.to_dict(), separators=(",", ":"), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return AnchorReceipt(
            sink=self.name,
            ref=f"{self.path.name}:{len(existing) + 1}",
            published_at=checkpoint.timestamp,
            detail={"path": str(self.path), "local": True},
        )


def read_checkpoints(anchor_file: Path) -> list[Checkpoint]:
    """Every checkpoint in the log, oldest first. Unreadable lines are skipped."""
    out: list[Checkpoint] = []
    if not Path(anchor_file).is_file():
        return out
    with Path(anchor_file).open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                out.append(Checkpoint.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    return out


# ----------------------------------------------------------------------
# Verification
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class CheckpointResult:
    checkpoint: Checkpoint
    ok: bool
    message: str


@dataclass(frozen=True)
class AnchorCoverage:
    """How much of the trail a set of checkpoints actually vouches for."""

    tree_size: int
    checkpoints: int
    anchored_through: int
    results: list[CheckpointResult]
    local_only: bool

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def unanchored(self) -> int:
        return max(0, self.tree_size - self.anchored_through)

    @property
    def failures(self) -> list[CheckpointResult]:
        return [r for r in self.results if not r.ok]


def verify_anchors(
    trail_path: Path, anchor_file: Path | None = None, *, local_only: bool = True
) -> AnchorCoverage:
    """Recompute each checkpoint's root from the trail and compare.

    The three ways this fails are distinct events and are reported as such:

    * the trail is now *shorter* than a checkpoint claimed — records were
      deleted, and no amount of rehashing hides it;
    * the root differs at the same tree size — a record below that point was
      edited and the chain rebuilt around it, which is precisely the attack the
      chain alone cannot see;
    * the checkpoint is malformed — says nothing about the trail either way, and
      must not be scored as a pass.
    """
    anchors = Path(anchor_file) if anchor_file else anchor_path(Path(trail_path))
    checkpoints = read_checkpoints(anchors)
    _, current_size = merkle_root(Path(trail_path))

    results: list[CheckpointResult] = []
    anchored_through = 0
    for cp in checkpoints:
        if cp.trail_name and cp.trail_name != Path(trail_path).name:
            results.append(
                CheckpointResult(cp, False, f"checkpoint is for a different trail ({cp.trail_name})")
            )
            continue
        try:
            root, _ = merkle_root(Path(trail_path), tree_size=cp.tree_size)
        except ValueError:
            results.append(
                CheckpointResult(
                    cp,
                    False,
                    f"trail now holds {current_size} records but was anchored at "
                    f"{cp.tree_size} on {cp.timestamp} — records were deleted",
                )
            )
            continue
        if root != cp.root_sha256:
            results.append(
                CheckpointResult(
                    cp,
                    False,
                    f"root at size {cp.tree_size} is {root[:16]}… but {cp.root_sha256[:16]}… "
                    f"was anchored on {cp.timestamp} — a record below that point was altered",
                )
            )
            continue
        results.append(
            CheckpointResult(cp, True, f"records 1-{cp.tree_size} match the anchor from {cp.timestamp}")
        )
        anchored_through = max(anchored_through, cp.tree_size)

    return AnchorCoverage(
        tree_size=current_size,
        checkpoints=len(checkpoints),
        anchored_through=anchored_through,
        results=results,
        local_only=local_only,
    )


def coverage_lines(coverage: AnchorCoverage) -> list[str]:
    """Human-readable coverage, phrased so it cannot be over-read.

    Kept next to the logic rather than in the CLI because the wording *is* the
    feature. The failure mode this whole module exists to correct is a reader
    taking a green check for more assurance than it carries, and that mistake is
    made in the sentence, not in the hash.
    """
    if not coverage.checkpoints:
        return [
            "  anchors: none — the chain verifies against itself only. "
            "A host-level attacker can rebuild it. See `agentmetry anchor --help`."
        ]

    lines = [f"  anchors: {coverage.checkpoints} checkpoint(s)"]
    for failure in coverage.failures:
        lines.append(f"    TAMPERING — {failure.message}")

    if coverage.anchored_through:
        lines.append(f"    records 1-{coverage.anchored_through} anchored")
        if coverage.unanchored:
            # Only records genuinely appended since the last good checkpoint are
            # "newer". Saying that about a range left uncovered by a *failed*
            # checkpoint would describe tampering as ordinary growth, which is
            # the one reading this output must never permit.
            lines.append(
                f"    records {coverage.anchored_through + 1}-{coverage.tree_size} "
                f"unanchored ({coverage.unanchored} newer) — chain-verified only, "
                "not a weaker chain but a weaker guarantee"
            )
    elif coverage.failures:
        lines.append("    no range is anchored — every checkpoint failed above")
    else:
        lines.append(f"    records 1-{coverage.tree_size} unanchored — chain-verified only")
    if coverage.local_only and not coverage.failures:
        lines.append(
            "    the anchor log is on this host, so it proves little until a copy "
            "lives somewhere this machine cannot write"
        )
    return lines
