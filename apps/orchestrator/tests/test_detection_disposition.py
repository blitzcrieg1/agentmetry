"""Detection triage — C1 from the 2026-07-24 release-readiness review.

The product recorded findings and stopped there. A detection nobody
dispositioned is an alert, not a control, and the compliance digest was already
asking for a triage note with nowhere to store it.

Two properties matter more than the CRUD and are tested hardest here:

1. the decision is an event on the trail, not just a row in a table, so it
   inherits the hash chain and reaches the SIEM; and
2. history is append-only, so "false positive" later becoming "confirmed"
   survives rather than being overwritten.
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit.detection.disposition import (
    CLOSED_STATUSES,
    DEFAULT_STATUS,
    DISPOSITION_EVENT_TYPE,
    STATUSES,
    DispositionError,
    DispositionStore,
    apply_disposition,
    build_disposition_event,
    detection_key,
    extract_dispositions,
    get_disposition_store,
    rebuild_from_trail,
    reset_disposition_store,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "detection_disposition_db_path", tmp_path / "disp.db")
    reset_disposition_store()
    yield get_disposition_store()
    reset_disposition_store()


# --- identity ----------------------------------------------------------------

def test_detection_key_is_stable_across_recomputation():
    """Rules are re-run over the trail, so identity is scope plus rule."""
    assert detection_key("sess-1", "credential-exfil") == detection_key(
        "sess-1", "credential-exfil"
    )
    assert detection_key("sess-1", "credential-exfil") != detection_key(
        "sess-2", "credential-exfil"
    )


def test_detection_key_requires_a_rule():
    with pytest.raises(DispositionError):
        detection_key("sess-1", "")


# --- validation --------------------------------------------------------------

def test_unknown_status_is_rejected(store):
    with pytest.raises(DispositionError):
        store.record(correlation_id="s1", rule_id="credential-exfil", status="probably_fine")


@pytest.mark.parametrize("status", ["false_positive", "risk_accepted"])
def test_closing_without_a_reason_is_rejected(store, status):
    """A bare 'false positive' is a dismissal wearing a disposition's clothes."""
    with pytest.raises(DispositionError):
        store.record(correlation_id="s1", rule_id="credential-exfil", status=status)
    assert store.get("s1", "credential-exfil") is None


@pytest.mark.parametrize("status", ["false_positive", "risk_accepted"])
def test_closing_with_a_reason_is_accepted(store, status):
    current = store.record(
        correlation_id="s1", rule_id="credential-exfil", status=status, note="known CI bot"
    )
    assert current["status"] == status
    assert current["note"] == "known CI bot"
    assert current["closed"] is True


def test_acknowledge_does_not_require_a_note(store):
    assert store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")


def test_an_overlong_note_is_rejected(store):
    with pytest.raises(DispositionError):
        store.record(
            correlation_id="s1", rule_id="credential-exfil", status="resolved", note="x" * 4001
        )


def test_every_status_is_settable(store):
    for status in STATUSES:
        note = "reason" if status in {"false_positive", "risk_accepted"} else ""
        assert store.record(
            correlation_id="s1", rule_id=status, status=status, note=note
        )["status"] == status


def test_closed_statuses_are_the_ones_that_end_a_finding():
    assert CLOSED_STATUSES == {"resolved", "false_positive", "risk_accepted"}
    assert DEFAULT_STATUS not in CLOSED_STATUSES


# --- history -----------------------------------------------------------------

def test_superseding_a_decision_keeps_the_previous_one(store):
    store.record(
        correlation_id="s1", rule_id="credential-exfil", status="false_positive", note="ci bot"
    )
    current = store.record(
        correlation_id="s1",
        rule_id="credential-exfil",
        status="in_progress",
        note="turned out to be real",
    )
    assert current["status"] == "in_progress"
    assert [h["status"] for h in current["history"]] == ["false_positive", "in_progress"]
    assert current["history"][0]["note"] == "ci bot"


def test_first_seen_survives_a_supersede(store):
    first = store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")
    second = store.record(correlation_id="s1", rule_id="credential-exfil", status="resolved")
    assert second["first_seen_utc"] == first["first_seen_utc"]
    assert second["decided_at_utc"] >= first["decided_at_utc"]


def test_an_untouched_detection_has_no_disposition(store):
    assert store.get("s1", "never-triaged") is None


def test_counts_group_by_status(store):
    store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")
    store.record(correlation_id="s2", rule_id="credential-exfil", status="acknowledged")
    store.record(correlation_id="s3", rule_id="session-tool-burst", status="resolved")
    assert store.counts() == {"acknowledged": 2, "resolved": 1}


def test_for_correlation_is_keyed_by_rule(store):
    store.record(correlation_id="s1", rule_id="credential-exfil", status="acknowledged")
    store.record(correlation_id="s1", rule_id="session-tool-burst", status="in_progress")
    store.record(correlation_id="s2", rule_id="credential-exfil", status="resolved")
    by_rule = store.for_correlation("s1")
    assert set(by_rule) == {"credential-exfil", "session-tool-burst"}
    assert by_rule["session-tool-burst"]["status"] == "in_progress"


# --- the decision is an event ------------------------------------------------

def test_disposition_event_is_canonical_and_alertable():
    event = build_disposition_event(
        correlation_id="s1",
        rule_id="credential-exfil",
        status="risk_accepted",
        note="internal test harness",
        decided_by="alex",
        severity="critical",
    )
    assert event["action"]["type"] == DISPOSITION_EVENT_TYPE
    # A SIEM must be able to alert on an accepted risk without knowing
    # Agentmetry's vocabulary.
    assert event["action"]["outcome"] == "risk_accepted"
    assert event["correlation_id"] == "s1"
    assert event["disposition"]["decided_by"] == "alex"
    assert event["disposition"]["previous_status"] == DEFAULT_STATUS
    assert event["event_id"]
    assert event["timestamp_utc"]


def test_extract_dispositions_ignores_other_events():
    events = [
        {"action": {"type": "tool_called"}},
        {"action": {"type": DISPOSITION_EVENT_TYPE}},  # no disposition block
        build_disposition_event(correlation_id="s1", rule_id="credential-exfil", status="resolved"),
    ]
    found = extract_dispositions(events)
    assert len(found) == 1
    assert found[0]["rule_id"] == "credential-exfil"


async def test_apply_disposition_writes_the_trail_before_the_index(
    store, tmp_path, monkeypatch
):
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_enabled", False)
    reset_trail_db()

    await apply_disposition(
        correlation_id="s1",
        rule_id="credential-exfil",
        status="risk_accepted",
        note="internal harness",
        decided_by="alex",
    )

    events = get_trail_db().events_by_action_type(DISPOSITION_EVENT_TYPE)
    assert len(events) == 1
    assert events[0]["disposition"]["status"] == "risk_accepted"
    assert store.get("s1", "credential-exfil")["status"] == "risk_accepted"
    reset_trail_db()


async def test_a_rejected_disposition_writes_nothing(store, tmp_path, monkeypatch):
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_enabled", False)
    reset_trail_db()

    with pytest.raises(DispositionError):
        await apply_disposition(
            correlation_id="s1", rule_id="credential-exfil", status="false_positive"
        )

    assert get_trail_db().events_by_action_type(DISPOSITION_EVENT_TYPE) == []
    assert store.get("s1", "credential-exfil") is None
    reset_trail_db()


async def test_a_down_sink_does_not_lose_the_decision(store, tmp_path, monkeypatch):
    """Forwarding is best-effort; the operator's decision is not."""
    from agentmetry.core.audit import ingest
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    reset_trail_db()

    class ExplodingSink:
        async def emit(self, _event):
            raise ConnectionError("SIEM down")

    monkeypatch.setattr(ingest, "_get_sink", lambda: ExplodingSink())

    await apply_disposition(
        correlation_id="s1", rule_id="credential-exfil", status="acknowledged", decided_by="alex"
    )
    assert store.get("s1", "credential-exfil")["status"] == "acknowledged"
    assert len(get_trail_db().events_by_action_type(DISPOSITION_EVENT_TYPE)) == 1
    reset_trail_db()


# --- the table is an index, the trail is the record --------------------------

async def test_the_index_rebuilds_from_the_trail(store, tmp_path, monkeypatch):
    from agentmetry.core.audit.trail_db import get_trail_db, reset_trail_db
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "audit_export_enabled", False)
    reset_trail_db()

    await apply_disposition(
        correlation_id="s1", rule_id="credential-exfil", status="false_positive", note="ci bot"
    )
    await apply_disposition(
        correlation_id="s1", rule_id="credential-exfil", status="in_progress", note="actually real"
    )
    await apply_disposition(correlation_id="s2", rule_id="session-tool-burst", status="acknowledged")

    store.clear()
    assert store.all() == []

    replayed = rebuild_from_trail(get_trail_db())
    assert replayed == 3
    # The last decision recorded is the one in force, and the earlier one is
    # still visible in history.
    current = store.get("s1", "credential-exfil")
    assert current["status"] == "in_progress"
    assert [h["status"] for h in current["history"]] == ["false_positive", "in_progress"]
    assert store.get("s2", "session-tool-burst")["status"] == "acknowledged"
    reset_trail_db()


def test_a_separate_store_path_is_isolated(tmp_path):
    a = DispositionStore(tmp_path / "a.db")
    b = DispositionStore(tmp_path / "b.db")
    a.record(correlation_id="s1", rule_id="credential-exfil", status="resolved")
    assert b.get("s1", "credential-exfil") is None


def test_disposition_event_carries_a_host_id():
    """A fleet forwarding to one SIEM must be able to attribute the decision.

    Every other canonical event carries host_id; this one was built by hand and
    omitted it, so "somebody accepted this risk" had no answer.
    """
    event = build_disposition_event(
        correlation_id="s1", rule_id="credential-exfil", status="acknowledged"
    )
    assert event["host_id"]


def test_fleet_id_is_absent_rather_than_empty_when_unset(monkeypatch):
    """An empty string on every event is noise in the trail and a trap in a SIEM.

    `fleet_id="*"` would then match unconfigured hosts, and excluding them would
    need an explicit `fleet_id!=""` on every query. Absent means absent.
    """
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "fleet_id", "")
    event = build_disposition_event(
        correlation_id="s1", rule_id="credential-exfil", status="acknowledged"
    )
    assert "fleet_id" not in event


def test_disposition_event_includes_configured_fleet_id(monkeypatch):
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "fleet_id", "pilot-east")
    event = build_disposition_event(
        correlation_id="s1", rule_id="credential-exfil", status="acknowledged"
    )
    assert event["fleet_id"] == "pilot-east"


def test_disposition_event_matches_the_canonical_envelope(monkeypatch):
    """Same top-level keys a SIEM parser already expects from detections."""
    from agentmetry.core.config import settings

    from agentmetry.core.audit.detection.live import build_detection_event
    from agentmetry.core.audit.detection.models import Detection

    monkeypatch.setattr(settings, "fleet_id", "pilot-east")
    detection = build_detection_event(
        Detection(rule_id="credential-exfil", title="t", severity="high", summary="s",
                  correlation_id="s1"),
        {"timestamp_utc": "2026-07-24T00:00:00+00:00"},
    )
    disposition = build_disposition_event(
        correlation_id="s1", rule_id="credential-exfil", status="acknowledged"
    )
    shared = {"schema_version", "event_id", "correlation_id", "timestamp_utc",
              "host_id", "fleet_id", "source", "actor", "initiator", "action", "agent"}
    assert shared <= set(detection)
    assert shared <= set(disposition)


# ----------------------------------------------------------------------
# Log injection (CodeQL py/log-injection, six alerts in this module)
#
# `rule_id`, `decided_by` and the disposition keys derived from `correlation_id`
# all originate outside this process. A newline in any of them let the writer
# append lines to the orchestrator log that look exactly like ours.
#
# `chr(92)` rather than an escaped backslash literal throughout: these
# assertions are about backslashes, and writing them as escapes makes the test
# harder to read than the thing it tests.
# ----------------------------------------------------------------------

BACKSLASH = chr(92)


def test_loggable_escapes_newlines_so_a_log_line_cannot_be_forged():
    from agentmetry.core.audit.detection.disposition import _loggable

    forged = _loggable("credential-exfil" + chr(10) + "INFO DISPOSITION other -> resolved")
    assert chr(10) not in forged, "a real newline survived, the log is forgeable"
    assert BACKSLASH + "n" in forged, "the newline should be visible as an escape"


def test_loggable_escapes_carriage_returns_and_other_control_characters():
    from agentmetry.core.audit.detection.disposition import _loggable

    for raw in ("a" + chr(13) + "b", "a" + chr(0) + "b", "a" + chr(27) + "[31mb"):
        out = _loggable(raw)
        assert not any(ord(c) < 0x20 for c in out), (raw, out)


def test_loggable_leaves_ordinary_values_untouched():
    """A sanitizer that mangles normal ids makes the log worse, not better."""
    from agentmetry.core.audit.detection.disposition import _loggable

    for raw in ("credential-exfil", "host-subagent-swarm-burst", "operator", "dev_01"):
        assert _loggable(raw) == raw


def test_loggable_truncates_rather_than_rendering_an_unbounded_string():
    from agentmetry.core.audit.detection.disposition import _loggable

    out = _loggable("x" * 5000)
    assert len(out) < 200
    assert out.endswith(BACKSLASH + "u2026")
