"""Hash-chained JSONL audit trail records (tamper-evident file sink).

Each file line is an envelope:

    {"trail": {"v": 1, "seq": N, "prev_sha256": "...", "record_sha256": "..."}, "event": {...}}

Legacy lines (plain canonical events) remain readable; verify reports them separately.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRAIL_VERSION = 1
GENESIS_SHA256 = hashlib.sha256(b"AGENTMETRY_TRAIL_GENESIS_v1").hexdigest()


def chain_sidecar_path(trail_path: Path) -> Path:
    return trail_path.with_name(trail_path.name + ".chain")


def canonical_event_json(event: dict[str, Any]) -> str:
    return json.dumps(event, separators=(",", ":"), sort_keys=True, default=str)


def compute_record_sha256(prev_sha256: str, event: dict[str, Any]) -> str:
    material = f"{prev_sha256}\n{canonical_event_json(event)}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def wrap_chained_record(seq: int, prev_sha256: str, event: dict[str, Any]) -> dict[str, Any]:
    record_sha256 = compute_record_sha256(prev_sha256, event)
    return {
        "trail": {
            "v": TRAIL_VERSION,
            "seq": seq,
            "prev_sha256": prev_sha256,
            "record_sha256": record_sha256,
        },
        "event": event,
    }


def unwrap_trail_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical event from an envelope or a legacy plain record."""
    if not isinstance(record, dict):
        return record
    trail = record.get("trail")
    event = record.get("event")
    if isinstance(trail, dict) and isinstance(event, dict):
        return event
    return record


def is_chained_record(record: dict[str, Any]) -> bool:
    trail = record.get("trail") if isinstance(record, dict) else None
    event = record.get("event") if isinstance(record, dict) else None
    return isinstance(trail, dict) and isinstance(event, dict)


@dataclass
class ChainHead:
    seq: int
    last_sha256: str


def _load_sidecar(sidecar: Path) -> ChainHead | None:
    if not sidecar.is_file():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return ChainHead(
            seq=int(data.get("seq", 0)),
            last_sha256=str(data.get("last_sha256") or GENESIS_SHA256),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _save_sidecar(sidecar: Path, head: ChainHead) -> None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({"seq": head.seq, "last_sha256": head.last_sha256}, indent=2) + "\n",
        encoding="utf-8",
    )


def _head_from_trail_file(trail_path: Path) -> ChainHead | None:
    if not trail_path.is_file():
        return None
    try:
        last_line = ""
        with trail_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    last_line = line.strip()
        if not last_line:
            return None
        record = json.loads(last_line)
        if not is_chained_record(record):
            return None
        trail = record["trail"]
        return ChainHead(seq=int(trail["seq"]), last_sha256=str(trail["record_sha256"]))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def load_chain_head(trail_path: Path) -> ChainHead:
    sidecar = chain_sidecar_path(trail_path)
    head = _load_sidecar(sidecar)
    if head is not None:
        return head
    recovered = _head_from_trail_file(trail_path)
    if recovered is not None:
        return recovered
    return ChainHead(seq=0, last_sha256=GENESIS_SHA256)


def append_chained_line(trail_path: Path, event: dict[str, Any]) -> ChainHead:
    """Append one chained envelope line and persist the sidecar head."""
    head = load_chain_head(trail_path)
    next_seq = head.seq + 1
    envelope = wrap_chained_record(next_seq, head.last_sha256, event)
    line = json.dumps(envelope, separators=(",", ":"), default=str) + "\n"
    trail_path.parent.mkdir(parents=True, exist_ok=True)
    with trail_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    new_head = ChainHead(seq=next_seq, last_sha256=envelope["trail"]["record_sha256"])
    _save_sidecar(chain_sidecar_path(trail_path), new_head)
    return new_head


@dataclass
class TrailVerifyResult:
    ok: bool
    message: str
    lines_total: int = 0
    lines_chained: int = 0
    lines_legacy: int = 0
    first_bad_line: int | None = None
    # The chain head after a successful walk. Printed by the CLI so an operator
    # can record it somewhere the audited agent cannot write and compare later —
    # the only defense a local file can offer against tail deletion.
    head_seq: int = 0
    head_sha256: str = ""


def verify_trail_file(trail_path: Path) -> TrailVerifyResult:
    if not trail_path.is_file():
        return TrailVerifyResult(False, f"no such file: {trail_path}")

    prev = GENESIS_SHA256
    expected_seq = 0
    total = chained = legacy = 0
    first_bad: int | None = None

    try:
        with trail_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line_no, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                total += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return TrailVerifyResult(
                        False,
                        f"invalid JSON at line {line_no}",
                        total,
                        chained,
                        legacy,
                        line_no,
                    )
                if not isinstance(record, dict):
                    return TrailVerifyResult(
                        False,
                        f"expected object at line {line_no}",
                        total,
                        chained,
                        legacy,
                        line_no,
                    )
                if not is_chained_record(record):
                    # Legacy lines are only legitimate as a prefix from before
                    # chaining was enabled. An unchained line AFTER chained
                    # records is exactly what a forged append looks like, and
                    # readers would render it as a real event.
                    if chained > 0:
                        return TrailVerifyResult(
                            False,
                            f"unchained line after chained records at line {line_no} (forged append?)",
                            total,
                            chained,
                            legacy,
                            line_no,
                        )
                    legacy += 1
                    continue

                trail = record["trail"]
                event = record["event"]
                seq = int(trail.get("seq", -1))
                prev_sha = str(trail.get("prev_sha256", ""))
                record_sha = str(trail.get("record_sha256", ""))

                if seq != expected_seq + 1:
                    return TrailVerifyResult(
                        False,
                        f"sequence break at line {line_no}: expected seq {expected_seq + 1}, got {seq}",
                        total,
                        chained,
                        legacy,
                        line_no,
                    )
                if prev_sha != prev:
                    return TrailVerifyResult(
                        False,
                        f"prev_sha256 mismatch at line {line_no}",
                        total,
                        chained,
                        legacy,
                        line_no,
                    )
                expected = compute_record_sha256(prev_sha, event)
                if record_sha != expected:
                    return TrailVerifyResult(
                        False,
                        f"record_sha256 mismatch at line {line_no} (tampered?)",
                        total,
                        chained,
                        legacy,
                        line_no,
                    )

                chained += 1
                expected_seq = seq
                prev = record_sha
    except OSError as exc:
        return TrailVerifyResult(False, f"read failed: {exc}")

    if chained == 0 and legacy > 0:
        return TrailVerifyResult(
            True,
            f"legacy trail only — {legacy} unchained line(s); enable export to start chaining",
            total,
            chained,
            legacy,
        )
    if chained == 0:
        return TrailVerifyResult(True, "empty trail", total, chained, legacy)

    # The chain itself proves in-place edits, inserts, and reordering. It cannot
    # prove the file was not cut short: compare against the sidecar head, which
    # records how far the writer actually got.
    sidecar_head = _load_sidecar(chain_sidecar_path(trail_path))
    if sidecar_head is not None and sidecar_head.seq > expected_seq:
        return TrailVerifyResult(
            False,
            f"trail ends at seq {expected_seq} but sidecar records seq {sidecar_head.seq} (truncated?)",
            total,
            chained,
            legacy,
        )
    if sidecar_head is not None and sidecar_head.seq == expected_seq and sidecar_head.last_sha256 != prev:
        return TrailVerifyResult(
            False,
            f"sidecar head hash does not match the last chained record at seq {expected_seq}",
            total,
            chained,
            legacy,
        )

    prefix = (
        f"{chained} chained line(s) verified; {legacy} legacy unchained prefix line(s)"
        if legacy
        else f"{chained} chained line(s) verified"
    )
    # A missing sidecar is legitimate (verifying a copied .jsonl on another
    # machine) but it means tail deletion cannot be ruled out — say so instead
    # of implying a stronger guarantee than the file alone can carry.
    if sidecar_head is None:
        prefix += "; no sidecar head found, so tail truncation cannot be ruled out"
    return TrailVerifyResult(
        True,
        prefix,
        total,
        chained,
        legacy,
        first_bad,
        head_seq=expected_seq,
        head_sha256=prev,
    )
