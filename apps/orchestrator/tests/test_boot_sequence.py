"""What survives a restart.

The orchestrator's lifespan runs three recovery steps behind broad
`except Exception` handlers: trail backfill, hook spool drain, and triage
reconcile. Each is deliberately non-fatal, because a recorder that refuses to
boot records nothing. The cost of that contract is that a step which silently
does the wrong thing looks identical to one that worked.

Wiring `rebuild_from_trail()` into boot on 2026-07-25 did exactly that. It
begins by emptying the triage index, so a pruned, rotated, restored or repointed
trail erased every disposition on the next start. The findings survived, so the
period read as *untriaged* rather than *unknown*, which is precisely backwards
for ISO/IEC 42001 cl. 10 corrective-action evidence.

These tests assert the recovery steps preserve rather than destroy.
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit.detection.disposition import (
    DispositionRebuildRefused,
    apply_disposition,
    get_disposition_store,
    rebuild_from_trail,
    reconcile_at_boot,
)
from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db


async def _decide(corr: str, rule: str, status: str = "acknowledged") -> None:
    # Closing states require a written reason; supply one so these tests
    # exercise the boot path rather than the validator.
    note = "boot-sequence fixture" if status in {"false_positive", "risk_accepted"} else ""
    await apply_disposition(
        correlation_id=corr, rule_id=rule, status=status, note=note
    )


def _prune_trail(tmp_path, monkeypatch, name: str = "pruned.db") -> None:
    """Repoint the trail at an empty database.

    Stands in for every way the record can stop accounting for the index:
    retention, a partial restore, a rotated file, or an operator changing
    AGENTMETRY_AUDIT_DB_PATH. Resetting the singleton alone would reopen the
    same file, which is not the failure being tested.
    """
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / name)
    reset_trail_db()
    get_trail_db()


# --- the reconcile step must never lose a decision ---------------------------

async def test_a_matching_trail_replays_cleanly():
    await _decide("s1", "credential-exfil")
    await _decide("s2", "session-tool-burst")
    store = get_disposition_store()

    assert rebuild_from_trail() == 2
    assert store.get("s1", "credential-exfil")["status"] == "acknowledged"
    assert store.get("s2", "session-tool-burst")["status"] == "acknowledged"


async def test_a_pruned_trail_is_refused_not_replayed(tmp_path, monkeypatch):
    """The failure that shipped: trail loses history, index gets emptied."""
    await _decide("s1", "credential-exfil")
    await _decide("s2", "session-tool-burst")
    _prune_trail(tmp_path, monkeypatch)

    with pytest.raises(DispositionRebuildRefused) as excinfo:
        rebuild_from_trail()
    assert "s1::credential-exfil" in excinfo.value.missing
    assert len(excinfo.value.missing) == 2


async def test_a_refused_rebuild_leaves_the_index_intact(tmp_path, monkeypatch):
    await _decide("s1", "credential-exfil", "risk_accepted")
    store = get_disposition_store()
    before = store.get("s1", "credential-exfil")
    _prune_trail(tmp_path, monkeypatch)

    with pytest.raises(DispositionRebuildRefused):
        rebuild_from_trail()

    after = store.get("s1", "credential-exfil")
    assert after == before, "triage history was destroyed by a rebuild"


async def test_force_accepts_the_loss_when_the_operator_asks(tmp_path, monkeypatch):
    await _decide("s1", "credential-exfil")
    _prune_trail(tmp_path, monkeypatch)

    assert rebuild_from_trail(force=True) == 0
    assert get_disposition_store().get("s1", "credential-exfil") is None


async def test_a_trail_with_extra_decisions_still_rebuilds():
    """A superset is safe: nothing in the index goes missing."""
    await _decide("s1", "credential-exfil")
    store = get_disposition_store()
    store.clear()
    await _decide("s2", "session-tool-burst")

    # Trail holds both; index holds only s2. Rebuild restores s1.
    assert rebuild_from_trail() == 2
    assert store.get("s1", "credential-exfil") is not None


# --- reconcile_at_boot degrades, it does not fail ----------------------------

async def test_boot_reconcile_declines_instead_of_raising(tmp_path, monkeypatch):
    await _decide("s1", "credential-exfil")
    _prune_trail(tmp_path, monkeypatch)

    assert reconcile_at_boot() == -1, "boot must not propagate the refusal"
    assert get_disposition_store().get("s1", "credential-exfil") is not None


async def test_boot_reconcile_replays_when_it_is_safe():
    await _decide("s1", "credential-exfil")
    get_disposition_store().clear()
    assert reconcile_at_boot() == 1


async def test_boot_reconcile_on_an_empty_install_is_a_no_op():
    assert reconcile_at_boot() == 0


# --- replayed rows keep their link back to the trail -------------------------

async def test_replay_preserves_the_trail_event_id():
    """Without this, a rebuilt row cannot be traced to the line that wrote it."""
    await _decide("s1", "credential-exfil")
    store = get_disposition_store()
    original = store.get("s1", "credential-exfil")["event_id"]
    assert original

    store.clear()
    rebuild_from_trail()
    assert store.get("s1", "credential-exfil")["event_id"] == original


# --- the whole lifespan, end to end ------------------------------------------

async def test_lifespan_boots_with_triage_intact(monkeypatch):
    """Start the real app and assert the recovery steps preserved state."""
    from fastapi.testclient import TestClient

    from agentmetry.api.main import app

    await _decide("s1", "credential-exfil", "risk_accepted")

    with TestClient(app):
        pass  # entering the context runs lifespan startup

    current = get_disposition_store().get("s1", "credential-exfil")
    assert current is not None, "boot destroyed the triage index"
    assert current["status"] == "risk_accepted"


async def test_lifespan_survives_a_broken_reconcile(monkeypatch):
    """A recorder that will not boot records nothing."""
    from fastapi.testclient import TestClient

    import agentmetry.core.audit.detection.disposition as disposition_module
    from agentmetry.api.main import app

    def _explode(*_a, **_kw):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(disposition_module, "reconcile_at_boot", _explode)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
