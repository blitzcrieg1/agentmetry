"""Rotation of the hash-chained trail into segments (pilot hardening item 20, #101).

The trail was one append-only file with no bound: about 70 MB and 28,000 lines
on the dogfood host, and every reader rescans all of it. A pilot's first
question about it is what happens when it fills the disk.

Rotation moves the active file, whole, into `<stem>.archive/` as
`<stem>.<first seq>-<last seq>.jsonl`, and the next append starts a new active
file. Nothing about the records changes. The chain continues across the
boundary (the first record of the new file has the last record of the old one
as its `prev_sha256`, and `seq` keeps counting), because the chain head lives
in the sidecar, not in the file. Every reader walks the segments in order, so:

- `verify --trail` verifies from genesis through every segment, as before;
- Merkle roots and anchors cover every record, so an anchor taken before a
  rotation still verifies after it;
- the forwarder follows its cursor from one segment into the next;
- dispositions replay from the SQLite index, which rotation does not touch.

What rotation deliberately does not do is delete anything. Retention (pruning
old segments) is a separate decision with a design in
docs/trail-retention.md, because a pruned segment changes what verification
and anchors can prove, and #101 rules out shipping that silently.

Off unless AGENTMETRY_TRAIL_ROTATE_BYTES is set, or `agentmetry trail rotate`
is run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

ARCHIVE_SUFFIX = ".archive"
MANIFEST_NAME = "segments.json"
_SEGMENT = re.compile(r"^(?P<stem>.+)\.(?P<first>\d{12})-(?P<last>\d{12})\.jsonl$")


def archive_dir(trail_path: Path) -> Path:
    return trail_path.with_name(trail_path.stem + ARCHIVE_SUFFIX)


def archived(trail_path: Path) -> list[Path]:
    """Archived segments, oldest first."""
    directory = archive_dir(trail_path)
    if not directory.is_dir():
        return []
    found = []
    for path in directory.iterdir():
        match = _SEGMENT.match(path.name)
        if match and match["stem"] == trail_path.stem:
            found.append((int(match["first"]), path))
    return [path for _, path in sorted(found)]


def segments(trail_path: Path) -> list[Path]:
    """Every file of the trail in order: archived segments, then the active file."""
    return [*archived(trail_path), trail_path]


def exists(trail_path: Path) -> bool:
    return any(path.is_file() for path in segments(trail_path))


def iter_lines(trail_path: Path) -> Iterator[tuple[Path, int, str]]:
    """(segment, line number within it, raw line) across the whole trail."""
    for path in segments(trail_path):
        try:
            fh = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line_no, raw in enumerate(fh, start=1):
                yield path, line_no, raw


def _chained_bounds(path: Path) -> tuple[dict, dict] | None:
    """The first and last chained `trail` headers in a file."""
    from agentmetry.core.audit.trail_chain import is_chained_record

    first = last = None
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                record = json.loads(raw)
            except ValueError:
                continue
            if is_chained_record(record):
                first = first or record["trail"]
                last = record["trail"]
    if first is None or last is None:
        return None
    return first, last


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rotate_locked(trail_path: Path) -> Path | None:
    """Archive the active file. The caller holds the trail's append lock."""
    if not trail_path.is_file() or trail_path.stat().st_size == 0:
        return None
    bounds = _chained_bounds(trail_path)
    if bounds is None:
        return None  # a legacy-only file has no seq range to name it by
    first, last = bounds
    directory = archive_dir(trail_path)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{trail_path.stem}.{int(first['seq']):012d}-{int(last['seq']):012d}.jsonl"
    if target.exists():
        raise FileExistsError(f"{target} already exists; refusing to overwrite an archived segment")
    entry = {
        "name": target.name,
        "first_seq": int(first["seq"]),
        "last_seq": int(last["seq"]),
        "first_prev_sha256": str(first.get("prev_sha256") or ""),
        "last_record_sha256": str(last.get("record_sha256") or ""),
        "bytes": trail_path.stat().st_size,
        "file_sha256": _file_sha256(trail_path),
        "rotated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    os.replace(trail_path, target)
    manifest = directory / MANIFEST_NAME
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = []
    entries.append(entry)
    tmp = manifest.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, manifest)
    return target


def rotate(trail_path: Path) -> Path | None:
    """Archive the active file now, under the same lock appends take."""
    from agentmetry.core.audit.trail_chain import _exclusive

    with _exclusive(trail_path):
        return rotate_locked(trail_path)


def manifest(trail_path: Path) -> list[dict]:
    try:
        return json.loads((archive_dir(trail_path) / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
