"""Evidence packs must be built from the audit trail, not the legacy outbox.

Regression for the 2026-07-24 finding: `build_evidence_pack` read the removed
governed runtime's event outbox and `runs.jsonl`. The hook ingest path never
published there, so on a recorder-only install the EU AI Act export contained
driver-mount noise while every captured agent tool call sat unexported in the
trail. These tests pin the source and the shape an auditor relies on.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.audit.evidence_pack import (
    build_evidence_pack,
    date_range_to_timestamps,
    verify_evidence_pack,
)


class _FakeTrail:
    def __init__(self, events):
        self._events = events
        self.calls: list[tuple[str, str]] = []

    def read_between(self, start_utc, end_utc, **_kwargs):
        self.calls.append((start_utc, end_utc))
        return list(self._events)


def _event(**overrides):
    base = {
        "schema_version": "1.1.0",
        "event_id": overrides.pop("event_id", "e-1"),
        "correlation_id": overrides.pop("correlation_id", "sess-1"),
        "timestamp_utc": overrides.pop("ts", "2026-07-22T10:00:00+00:00"),
        "source": {"tier": "external", "app": overrides.pop("app", "cursor")},
        "initiator": {"actor_type": overrides.pop("actor_type", "agent")},
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
    }
    base.update(overrides)
    return base


def _tool_event(qualified="cursor.Read", outcome="success", **extra):
    event = _event(**extra)
    event["action"] = {"type": "tool_called", "outcome": outcome, "reason": ""}
    event.setdefault("tool", {
        "qualified": qualified,
        "server": "cursor",
        "input_hash": "a" * 64,
        "mitre": {"tactic_id": "TA0006", "technique_id": "T1552.004"},
    })
    return event


@pytest.fixture
def dates():
    return date(2026, 7, 22), date(2026, 7, 22)


def test_pack_reads_the_trail_over_the_query_window(dates):
    from_date, to_date = dates
    trail = _FakeTrail([_tool_event()])
    pack = build_evidence_pack(from_date, to_date, trail_db=trail)

    assert trail.calls, "evidence pack must query the audit trail"
    assert trail.calls[0] == date_range_to_timestamps(from_date, to_date)
    assert pack["meta"]["source"] == "audit_trail"
    assert pack["summary"]["event_count"] == 1
    assert pack["summary"]["tool_calls"] == 1


def test_tool_calls_carry_hash_mitre_and_verdicts(dates):
    from_date, to_date = dates
    event = _tool_event()
    event["dlp"] = {"rule_id": "aws_access_key", "mode": "log"}
    event["tool_policy"] = {"rule_id": "block_shell_rm", "blocked": True}
    pack = build_evidence_pack(from_date, to_date, trail_db=_FakeTrail([event]))

    call = pack["tool_calls"][0]
    assert call["input_hash"] == "a" * 64
    assert call["technique_id"] == "T1552.004"
    assert call["dlp_rule_id"] == "aws_access_key"
    assert call["tool_policy_rule_id"] == "block_shell_rm"
    assert pack["summary"]["dlp_hits"] == {"aws_access_key": 1}


def test_denied_calls_are_counted_separately(dates):
    from_date, to_date = dates
    events = [_tool_event(), _tool_event(event_id="e-2", outcome="denied")]
    pack = build_evidence_pack(from_date, to_date, trail_db=_FakeTrail(events))
    assert pack["summary"]["tool_calls"] == 1
    assert pack["summary"]["tool_denials"] == 1


def test_inferred_approvals_are_flagged_for_the_auditor(dates):
    """An inferred response must never look like an observed human decision."""
    from_date, to_date = dates
    request = _event(event_id="req-1")
    request["action"] = {"type": "approval_request", "outcome": "pending", "reason": ""}
    request["tool"] = {"qualified": "shell.run", "input_hash": "b" * 64}

    response = _event(event_id="res-1", ts="2026-07-22T10:00:05+00:00")
    response["action"] = {
        "type": "approval_response",
        "outcome": "success",
        "reason": "inferred:tool_ran_after_ask",
    }
    response["gated_action"] = {"tool": "shell.run", "input_hash": "b" * 64}

    pack = build_evidence_pack(
        from_date, to_date, trail_db=_FakeTrail([request, response])
    )
    gate = pack["approvals"][0]
    assert gate["decision"] == "granted"
    assert gate["inferred"] is True
    assert pack["summary"]["approvals_inferred"] == 1


def test_approval_binds_on_input_hash_not_tool_name(dates):
    from_date, to_date = dates
    req_a = _event(event_id="req-a")
    req_a["action"] = {"type": "approval_request", "outcome": "pending", "reason": ""}
    req_a["tool"] = {"qualified": "shell.run", "input_hash": "1" * 64}

    req_b = _event(event_id="req-b", ts="2026-07-22T10:00:01+00:00")
    req_b["action"] = {"type": "approval_request", "outcome": "pending", "reason": ""}
    req_b["tool"] = {"qualified": "shell.run", "input_hash": "2" * 64}

    response = _event(event_id="res-b", ts="2026-07-22T10:00:09+00:00")
    response["action"] = {"type": "approval_response", "outcome": "success", "reason": ""}
    response["gated_action"] = {"tool": "shell.run", "input_hash": "2" * 64}

    pack = build_evidence_pack(
        from_date, to_date, trail_db=_FakeTrail([req_a, req_b, response])
    )
    by_hash = {g["input_hash"]: g for g in pack["approvals"]}
    assert by_hash["2" * 64]["decision"] == "granted"
    assert by_hash["1" * 64]["decision"] == "pending"


def test_detections_are_a_first_class_section(dates):
    from_date, to_date = dates
    detection = _event(event_id="det-1")
    detection["action"] = {
        "type": "detection",
        "outcome": "critical",
        "reason": "credential exfil",
    }
    detection["detection"] = {
        "rule_id": "credential-exfil",
        "title": "Credential access followed by network egress",
        "severity": "critical",
        "summary": "…",
        "event_ids": ["e-1", "e-2"],
    }
    pack = build_evidence_pack(from_date, to_date, trail_db=_FakeTrail([detection]))
    assert pack["detections"][0]["rule_id"] == "credential-exfil"
    assert pack["summary"]["detections_by_severity"] == {"critical": 1}


def test_controls_snapshot_records_enforcement_state(dates):
    from_date, to_date = dates
    pack = build_evidence_pack(from_date, to_date, trail_db=_FakeTrail([]))
    controls = pack["controls"]
    assert controls["dlp"]["manifest"]["present"] is True
    assert controls["dlp"]["manifest"]["sha256"]
    assert controls["tool_policy"]["manifest"]["present"] is True
    assert "mode" in controls["dlp"] and "mode" in controls["tool_policy"]


def test_pack_binds_to_the_trail_chain(dates):
    from_date, to_date = dates
    pack = build_evidence_pack(from_date, to_date, trail_db=_FakeTrail([]))
    assert "trail_chain" in pack["meta"]
    assert "head_sha256" in pack["meta"]["trail_chain"]


def test_integrity_hash_round_trips_and_detects_tampering(dates):
    from_date, to_date = dates
    pack = build_evidence_pack(
        from_date, to_date, trail_db=_FakeTrail([_tool_event()])
    )
    ok, message = verify_evidence_pack(pack)
    assert ok, message

    pack["tool_calls"][0]["tool"] = "cursor.SomethingElse"
    ok, message = verify_evidence_pack(pack)
    assert not ok and "integrity mismatch" in message


def test_compliance_mapping_states_scope_limits(dates):
    from_date, to_date = dates
    pack = build_evidence_pack(from_date, to_date, trail_db=_FakeTrail([]))
    mapping = pack["compliance_mapping"]
    assert "scope_limits" in mapping, "pack must state what it does NOT cover"
    assert "disclaimer" in mapping
    for article in ("art_12_logging", "art_14_human_oversight", "art_15_cybersecurity"):
        assert article in mapping


def test_include_raw_events_false_keeps_derived_sections(dates):
    from_date, to_date = dates
    pack = build_evidence_pack(
        from_date, to_date, trail_db=_FakeTrail([_tool_event()]), include_raw_events=False
    )
    assert pack["events"] == []
    assert pack["tool_calls"], "derived sections survive without raw events"
    ok, _ = verify_evidence_pack(pack)
    assert ok


def test_rejects_inverted_date_range():
    with pytest.raises(ValueError):
        build_evidence_pack(
            date.today(), date.today() - timedelta(days=1), trail_db=_FakeTrail([])
        )
