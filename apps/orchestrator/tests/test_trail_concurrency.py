"""Two processes appending to one trail must not lose events or break the chain.

`append_chained_line` is a read-modify-write: read the head, compute the next
seq and hash, append, save the sidecar. More than one process does this to the
same file. The orchestrator writes through `FileAuditSink`, and so does any CLI
that appends -- `import-agt` most directly. `sinks.py` holds a `threading.Lock`,
which serialises threads inside one process and does nothing whatsoever across
two.

Measured before the lock existed, two processes appending 25 events each:

    50 appends attempted
    43 lines written        7 events lost outright
    14 duplicate seq values
    verify_trail_file       sequence break at line 5

Both halves matter. Lost events are a gap in an audit trail, and a chain that
stops verifying at line 5 discards the evidentiary value of everything after it.
No attacker and no crash is required; two ordinary writers are enough.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from agentmetry.core.audit.trail_chain import (
    append_chained_line,
    lock_path,
    verify_trail_file,
)

_ORCHESTRATOR = Path(__file__).resolve().parents[1]

_WRITER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[4])
    from agentmetry.core.audit.trail_chain import append_chained_line
    trail, tag, delay = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
    time.sleep(delay)
    for i in range(int(sys.argv[5])):
        append_chained_line(trail, {"event_id": f"{tag}-{i}", "who": tag})
    """
)


def _spawn(script: Path, trail: Path, tag: str, count: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, str(script), str(trail), tag, "0.3", str(_ORCHESTRATOR), str(count)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.slow
def test_concurrent_processes_do_not_corrupt_the_chain(tmp_path):
    script = tmp_path / "writer.py"
    script.write_text(_WRITER, encoding="utf-8")
    trail = tmp_path / "trail.jsonl"

    per_writer, writers = 20, ("A", "B", "C")
    procs = [_spawn(script, trail, tag, per_writer) for tag in writers]
    for p in procs:
        _, err = p.communicate(timeout=180)
        assert p.returncode == 0, err.decode("utf-8", "replace")[-400:]

    lines = [
        json.loads(line)
        for line in trail.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    seqs = [line["trail"]["seq"] for line in lines]
    expected = per_writer * len(writers)

    assert len(lines) == expected, f"{expected - len(lines)} event(s) lost"
    assert len(set(seqs)) == expected, "duplicate seq values"
    assert seqs == list(range(1, expected + 1)), "seq values are not contiguous"

    result = verify_trail_file(trail)
    assert result.ok, result.message

    # Every writer's events survived, not just the winner of the race.
    authors = {json.loads(json.dumps(line["event"]))["who"] for line in lines}
    assert authors == set(writers)


def test_a_lock_file_is_created_beside_the_trail(tmp_path):
    trail = tmp_path / "trail.jsonl"
    append_chained_line(trail, {"event_id": "e1"})
    assert lock_path(trail).is_file()
    assert lock_path(trail).name == "trail.jsonl.lock"


def test_single_process_appends_are_unaffected(tmp_path):
    """The lock must not change the shape of what gets written."""
    trail = tmp_path / "trail.jsonl"
    for i in range(5):
        head = append_chained_line(trail, {"event_id": f"e{i}"})
    assert head.seq == 5
    assert verify_trail_file(trail).ok


def test_the_lock_file_is_not_mistaken_for_trail_content(tmp_path):
    """It sits in the same directory, so anything globbing the trail could pick
    it up. It must not parse as JSONL or appear as a chained record."""
    trail = tmp_path / "trail.jsonl"
    append_chained_line(trail, {"event_id": "e1"})
    from agentmetry.core.audit.trail_merkle import read_leaves

    assert len(read_leaves(trail)) == 1
    assert lock_path(trail).suffix == ".lock"


# ----------------------------------------------------------------------
# Canonical form must be injective
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "a", "b"),
    [
        (
            "datetime vs its own string form",
            {"ts": __import__("datetime").datetime(2026, 8, 8)},
            {"ts": "2026-08-08 00:00:00"},
        ),
        (
            "Decimal vs string",
            {"amount": __import__("decimal").Decimal("1.0")},
            {"amount": "1.0"},
        ),
        ("set vs its repr", {"tags": {"a"}}, {"tags": "{'a'}"}),
    ],
)
def test_non_json_values_cannot_collapse_into_another_event(label, a, b):
    """`default=str` is the obvious choice and quietly breaks the one property
    the canonical form exists for.

    `str()` is not injective across types, so a value and its own string form
    serialised to identical bytes and produced the same record hash. Two
    logically different events, one hash, in the function whose entire job is to
    tell records apart.

    Nothing reached it (all 5,610 lines of the live trail serialised with no
    fallback), which made it a trap rather than a bug: the kind that springs the
    day somebody puts a datetime in an event.
    """
    from agentmetry.core.audit.trail_chain import compute_record_sha256

    assert compute_record_sha256("prev", a) != compute_record_sha256("prev", b), label


def test_the_fallback_records_rather_than_refuses():
    """Tagging rather than raising keeps the recorder fail-open. An unserialisable
    value is still recorded, just unambiguously; refusing to record is the one
    outcome an audit trail cannot justify."""
    from agentmetry.core.audit.trail_chain import canonical_event_json

    class Odd:
        def __str__(self):
            return "odd"

    out = canonical_event_json({"x": Odd()})
    assert "Odd" in out and "odd" in out


def test_ordinary_json_events_are_untouched():
    """The fallback must never fire for normal events, or every stored hash
    would change and every existing trail would stop verifying."""
    from agentmetry.core.audit.trail_chain import canonical_event_json

    assert canonical_event_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert "__type__" not in canonical_event_json(
        {"event_id": "e1", "tool": {"name": "Bash", "traits": ["x"]}, "n": 1.5, "ok": True, "z": None}
    )
