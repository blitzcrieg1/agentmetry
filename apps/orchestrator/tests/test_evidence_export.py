"""Compliance evidence export — outbox + run ledger → JSON pack + integrity hash."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import core.notifiers.audit as audit_module
from core.audit.evidence_pack import (
    build_evidence_pack,
    date_range_to_timestamps,
    verify_evidence_pack,
    write_evidence_pack,
)
from core.bus.events import RUN_COMPLETED, RUN_STARTED, RUN_TERMINATED, RUN_WAITING, TOOL_CALLED
from core.bus.outbox import EventOutbox


def _seed_outbox(db_path: Path) -> EventOutbox:
    box = EventOutbox(db_path)
    events = [
        ("2026-07-05T10:00:00+00:00", RUN_STARTED, "t1", "sess-1", {"skill": "customer_reply"}),
        ("2026-07-05T10:01:00+00:00", TOOL_CALLED, "t1", "sess-1", {
            "tool": "gmail.get_thread", "skill": "customer_reply", "sandboxed": False,
        }),
        ("2026-07-05T10:02:00+00:00", RUN_WAITING, "t1", "sess-1", {
            "type": "approval_required", "draft": "Dear customer...", "confidence": 0.42,
        }),
        ("2026-07-05T10:05:00+00:00", RUN_COMPLETED, "t1", "sess-1", {
            "type": "execution_completed", "archive_path": "30-Archive/x.md",
            "metrics": {"cost": 0.01},
        }),
        ("2026-07-05T11:00:00+00:00", RUN_STARTED, "t2", "sess-2", {"skill": "lead_gen"}),
        ("2026-07-05T11:01:00+00:00", RUN_TERMINATED, "t2", "sess-2", {
            "type": "execution_terminated",
        }),
    ]
    for i, (ts, topic, tid, sid, payload) in enumerate(events, start=1):
        with box._lock, box._conn:
            box._conn.execute(
                "INSERT INTO events (seq, ts, topic, session_id, thread_id, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (i, ts, topic, sid, tid, json.dumps(payload)),
            )
    return box


def _seed_runs(path: Path) -> None:
    rows = [
        {"ts": "2026-07-05T10:00:00+00:00", "thread_id": "t1", "skill": "customer_reply",
         "status": "waiting_for_input", "session_id": "sess-1", "triggered_by": "manual"},
        {"ts": "2026-07-05T10:05:00+00:00", "thread_id": "t1", "skill": "customer_reply",
         "status": "approved", "session_id": "sess-1", "cost": 0.01,
         "archive_path": "30-Archive/x.md"},
        {"ts": "2026-07-05T11:00:00+00:00", "thread_id": "t2", "skill": "lead_gen",
         "status": "terminated", "session_id": "sess-2"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture
def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from core.config import settings

    db = tmp_path / "events.db"
    runs = tmp_path / "runs.jsonl"
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_outbox(db)
    _seed_runs(runs)
    monkeypatch.setattr(audit_module, "audit_path", lambda: runs)
    monkeypatch.setattr(settings, "vault_path", vault)
    yield EventOutbox(db), vault


def test_date_range_to_timestamps():
    start, end = date_range_to_timestamps(date(2026, 7, 1), date(2026, 7, 31))
    assert start.startswith("2026-07-01")
    assert end.startswith("2026-07-31")


def test_build_evidence_pack_contents(wired):
    box, vault = wired
    pack = build_evidence_pack(date(2026, 7, 5), date(2026, 7, 5), outbox=box, vault_path=vault)

    assert pack["meta"]["schema_version"] == "1.1"
    assert pack["meta"]["integrity_sha256"]
    assert pack["meta"]["provider_metadata"]["provider"]
    assert pack["summary"]["event_count"] == 6
    assert pack["summary"]["tool_calls"] == 1
    assert pack["summary"]["approvals_granted"] == 1
    assert len(pack["approvals"]) == 1
    approved = pack["approvals"][0]
    assert approved["thread_id"] == "t1"
    assert approved["decision"] == "approved"
    assert approved["draft"] == "Dear customer..."
    assert approved["confidence_score"] == 0.42
    assert approved["approval_signature"]
    assert len(approved["approval_signature"]) == 64
    terminated_run = next(r for r in pack["runs"] if r["thread_id"] == "t2")
    assert terminated_run["status"] == "terminated"


def test_integrity_hash_stable_and_verifiable(wired, tmp_path: Path):
    box, vault = wired
    pack = build_evidence_pack(date(2026, 7, 5), date(2026, 7, 5), outbox=box, vault_path=vault)
    path = tmp_path / "evidence.json"
    write_evidence_pack(pack, path)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    ok, msg = verify_evidence_pack(loaded)
    assert ok, msg

    pack2 = build_evidence_pack(date(2026, 7, 5), date(2026, 7, 5), outbox=box, vault_path=vault)
    assert pack2["meta"]["integrity_sha256"] == pack["meta"]["integrity_sha256"]


def test_tampered_pack_fails_verify(wired):
    box, vault = wired
    pack = build_evidence_pack(date(2026, 7, 5), date(2026, 7, 5), outbox=box, vault_path=vault)
    pack["events"][0]["topic"] = "run/tampered"
    ok, msg = verify_evidence_pack(pack)
    assert not ok
    assert "mismatch" in msg


def test_events_outside_range_excluded(wired):
    box, vault = wired
    pack = build_evidence_pack(date(2026, 6, 1), date(2026, 6, 30), outbox=box, vault_path=vault)
    assert pack["summary"]["event_count"] == 0
