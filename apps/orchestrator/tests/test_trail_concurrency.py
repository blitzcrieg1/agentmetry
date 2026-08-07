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
