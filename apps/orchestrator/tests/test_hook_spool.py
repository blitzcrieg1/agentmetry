"""Hook spool — events must survive a down orchestrator.

Regression for F4 (2026-07-20 review): `post_ingest` printed to stderr and
dropped the payload when the orchestrator was unreachable. Hooks fail open by
design (recording must never break the IDE), but the event was gone — so every
restart, update and IDE-launch race silently punched holes in the trail.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError

import pytest

from core.audit.spool import (
    MAX_AGE_SECONDS,
    drain_spool,
    expired_path,
    read_spool,
    spool_depth,
    spool_oldest_age_seconds,
)

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "scripts"))

import agentmetry_ingest as ingest  # noqa: E402


def _spool_line(payload, *, spooled_at=None):
    return json.dumps({
        "spooled_at": spooled_at or datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    })


def _payload(corr="sess-1"):
    return {
        "source_app": "cursor",
        "event_type": "tool_called",
        "correlation_id": corr,
        "tool": {"qualified": "cursor.Read", "server": "cursor", "input_hash": "a" * 64},
    }


# --- hook side ----------------------------------------------------------------

def test_unreachable_orchestrator_spools_instead_of_dropping(tmp_path, monkeypatch):
    spool = tmp_path / "hook-spool.jsonl"
    monkeypatch.setattr(ingest, "_spool_path", lambda: spool)

    def _boom(*_a, **_k):
        raise URLError("connection refused")

    monkeypatch.setattr(ingest.urllib.request, "urlopen", _boom)

    assert ingest.post_ingest(_payload(), quiet=True) is False
    assert spool.is_file(), "payload must be spooled, not dropped"

    rows = [json.loads(line) for line in spool.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["payload"]["correlation_id"] == "sess-1"
    assert rows[0]["spooled_at"]


def test_selftest_probe_is_never_spooled(tmp_path, monkeypatch):
    """A liveness probe is not captured activity; replaying it would inject
    synthetic events into the trail."""
    spool = tmp_path / "hook-spool.jsonl"
    monkeypatch.setattr(ingest, "_spool_path", lambda: spool)
    monkeypatch.setattr(
        ingest.urllib.request, "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(URLError("down")),
    )

    assert ingest.selftest() == 1
    assert not spool.exists(), "selftest must not leave synthetic events to replay"


def test_spool_stops_growing_past_the_size_cap(tmp_path, monkeypatch):
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text("x" * (ingest._SPOOL_MAX_BYTES + 1), encoding="utf-8")
    monkeypatch.setattr(ingest, "_spool_path", lambda: spool)
    assert ingest.spool_payload(_payload()) is False


def test_spool_write_failure_is_swallowed(tmp_path, monkeypatch):
    """The hook must never crash the IDE, whatever the filesystem does."""
    monkeypatch.setattr(
        ingest, "_spool_path", lambda: tmp_path / "nope" / "deep" / "spool.jsonl"
    )
    monkeypatch.setattr(Path, "mkdir", lambda *_a, **_k: (_ for _ in ()).throw(OSError()))
    assert ingest.spool_payload(_payload()) is False


# --- orchestrator side --------------------------------------------------------

def test_read_spool_returns_payloads_in_order(tmp_path):
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text(
        "\n".join(_spool_line(_payload(f"sess-{i}")) for i in range(3)) + "\n",
        encoding="utf-8",
    )
    payloads, dropped = read_spool(spool)
    assert [p["correlation_id"] for p in payloads] == ["sess-0", "sess-1", "sess-2"]
    assert dropped == 0


def test_read_spool_drops_stale_and_corrupt_rows(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(seconds=MAX_AGE_SECONDS + 60)).isoformat()
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text(
        "\n".join([
            _spool_line(_payload("fresh")),
            _spool_line(_payload("stale"), spooled_at=old),
            "{not json",
            json.dumps({"spooled_at": "now", "payload": "not-a-dict"}),
        ]) + "\n",
        encoding="utf-8",
    )
    payloads, dropped = read_spool(spool)
    assert [p["correlation_id"] for p in payloads] == ["fresh"]
    assert dropped == 3


def test_read_spool_missing_file_is_not_an_error(tmp_path):
    assert read_spool(tmp_path / "absent.jsonl") == ([], 0)


@pytest.mark.asyncio
async def test_drain_replays_through_ingest_and_removes_the_spool(tmp_path, monkeypatch):
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text(
        "\n".join(_spool_line(_payload(f"sess-{i}")) for i in range(2)) + "\n",
        encoding="utf-8",
    )

    seen = []

    async def _fake_ingest(payload):
        seen.append(payload["correlation_id"])
        return {}

    import core.audit.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ingest_external_event", _fake_ingest)

    result = await drain_spool(spool)
    assert result["replayed"] == 2
    assert seen == ["sess-0", "sess-1"]
    assert not spool.exists(), "a fully drained spool must be removed"


@pytest.mark.asyncio
async def test_failed_replay_keeps_the_spool_for_the_next_boot(tmp_path, monkeypatch):
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text(_spool_line(_payload()) + "\n", encoding="utf-8")

    async def _fail(_payload):
        raise RuntimeError("no sinks configured")

    import core.audit.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ingest_external_event", _fail)

    result = await drain_spool(spool)
    assert result["replayed"] == 0 and result["failed"] == 1
    # It survives under the rotated name, and the next drain picks it up.
    assert list(tmp_path.glob("hook-spool.jsonl.draining.*")), (
        "an undelivered event must survive to the next drain"
    )


@pytest.mark.asyncio
async def test_expired_payloads_are_quarantined_not_deleted(tmp_path):
    """A gap in an audit trail is a fact about the trail, not something to forget.

    These payloads cannot be replayed — injecting a week-old tool call into
    today's correlation window invents sequences that never happened — but the
    evidence that they existed has to outlive the drain.
    """
    old = (datetime.now(timezone.utc) - timedelta(seconds=MAX_AGE_SECONDS + 60)).isoformat()
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text(_spool_line(_payload("ancient"), spooled_at=old) + "\n", encoding="utf-8")

    result = await drain_spool(spool)
    assert result["replayed"] == 0 and result["expired"] == 1
    assert not spool.exists()

    quarantine = expired_path(spool)
    assert quarantine.is_file(), "an expired payload must be quarantined, never dropped"
    kept = json.loads(quarantine.read_text(encoding="utf-8").splitlines()[0])
    assert kept["payload"]["correlation_id"] == "ancient"


@pytest.mark.asyncio
async def test_events_spooled_during_a_drain_are_not_deleted(tmp_path, monkeypatch):
    """The bug that cost five days of real capture.

    The drain used to read the whole file, replay it, then unlink the path. On a
    machine busy enough to build a backlog the hooks keep appending throughout,
    so the unlink destroyed every event captured during the drain — silently,
    and worst exactly where the spool matters most.
    """
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text(
        "\n".join(_spool_line(_payload(f"old-{i}")) for i in range(3)) + "\n",
        encoding="utf-8",
    )

    seen = []

    async def _slow_ingest(payload):
        seen.append(payload["correlation_id"])
        # A hook fires while the drain is still working.
        with spool.open("a", encoding="utf-8") as fh:
            fh.write(_spool_line(_payload(f"during-{len(seen)}")) + "\n")
        return {}

    import core.audit.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ingest_external_event", _slow_ingest)

    result = await drain_spool(spool)
    assert result["replayed"] == 3
    assert seen == ["old-0", "old-1", "old-2"]

    survivors, _ = read_spool(spool)
    assert [p["correlation_id"] for p in survivors] == ["during-1", "during-2", "during-3"], (
        "events captured during the drain must survive it"
    )


@pytest.mark.asyncio
async def test_drain_resumes_a_rotated_file_left_by_a_crash(tmp_path, monkeypatch):
    """A process killed mid-drain leaves a rotated file. Nobody comes back for it
    unless the next drain looks."""
    spool = tmp_path / "hook-spool.jsonl"
    orphan = tmp_path / "hook-spool.jsonl.draining.20260101T000000.0"
    orphan.write_text(_spool_line(_payload("orphaned")) + "\n", encoding="utf-8")
    spool.write_text(_spool_line(_payload("current")) + "\n", encoding="utf-8")

    seen = []

    async def _fake_ingest(payload):
        seen.append(payload["correlation_id"])
        return {}

    import core.audit.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "ingest_external_event", _fake_ingest)

    result = await drain_spool(spool)
    assert result["replayed"] == 2
    assert seen == ["orphaned", "current"], "the older rotated file replays first"
    assert not orphan.exists() and not spool.exists()


def test_depth_counts_rotated_files_too(tmp_path):
    """Depth is what the operator acts on, so it has to include work in flight."""
    spool = tmp_path / "hook-spool.jsonl"
    spool.write_text("\n".join(_spool_line(_payload()) for _ in range(2)) + "\n", encoding="utf-8")
    (tmp_path / "hook-spool.jsonl.draining.20260101T000000.0").write_text(
        _spool_line(_payload()) + "\n", encoding="utf-8"
    )
    assert spool_depth(spool) == 3


def test_oldest_age_is_the_countdown_to_unreplayable(tmp_path):
    spool = tmp_path / "hook-spool.jsonl"
    two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    spool.write_text(
        "\n".join([
            _spool_line(_payload("older"), spooled_at=two_hours_ago),
            _spool_line(_payload("newer")),
        ]) + "\n",
        encoding="utf-8",
    )
    age = spool_oldest_age_seconds(spool)
    assert age is not None and 7000 < age < 7400


def test_oldest_age_is_none_when_nothing_is_pending(tmp_path):
    assert spool_oldest_age_seconds(tmp_path / "absent.jsonl") is None
