"""Tests for the correlated sequence-detection engine.

All events are synthetic — never real secrets in fixtures (gitleaks runs in CI).
"""

from __future__ import annotations

from core.audit.detection import run_detections


def _event(
    ts: str,
    *,
    action_type: str = "tool_called",
    outcome: str = "success",
    actor_type: str = "human",
    tool: str = "",
    tactic_id: str = "",
    technique_id: str = "",
    correlation_id: str = "sess-1",
    event_id: str = "",
) -> dict:
    event: dict = {
        "event_id": event_id or f"e-{ts}",
        "correlation_id": correlation_id,
        "timestamp_utc": ts,
        "initiator": {"actor_type": actor_type, "trigger": "manual", "operator_id": "local"},
        "action": {"type": action_type, "outcome": outcome, "reason": ""},
    }
    if tool:
        event["tool"] = {"qualified": tool}
        if tactic_id or technique_id:
            event["tool"]["mitre"] = {"tactic_id": tactic_id, "technique_id": technique_id}
    return event


def _rule_ids(events: list[dict]) -> set[str]:
    return {d.rule_id for d in run_detections(events)}


# --- credential-exfil --------------------------------------------------------

def test_credential_exfil_fires():
    events = [
        _event("2026-07-13T10:00:00Z", tool="shell.cat", tactic_id="TA0006", technique_id="T1552.004"),
        _event("2026-07-13T10:00:05Z", tool="shell.curl", tactic_id="TA0011", technique_id="T1071.001"),
    ]
    dets = run_detections(events)
    assert len(dets) == 1
    d = dets[0]
    assert d.rule_id == "credential-exfil"
    assert d.severity == "critical"
    assert d.tactic_ids == ["TA0006", "TA0011"]
    assert len(d.event_ids) == 2


def test_credential_exfil_does_not_fire_without_egress():
    events = [
        _event("2026-07-13T10:00:00Z", tool="shell.cat", tactic_id="TA0006", technique_id="T1552.004"),
        _event("2026-07-13T10:00:05Z", tool="vault_fs.read_file", tactic_id="TA0009", technique_id="T1005"),
    ]
    assert "credential-exfil" not in _rule_ids(events)


def test_credential_exfil_requires_network_after_not_before():
    # Network egress happens BEFORE the credential read — not exfil of that secret.
    events = [
        _event("2026-07-13T10:00:00Z", tool="shell.curl", tactic_id="TA0011", technique_id="T1071.001"),
        _event("2026-07-13T10:00:05Z", tool="shell.cat", tactic_id="TA0006", technique_id="T1552.004"),
    ]
    assert "credential-exfil" not in _rule_ids(events)


# --- autonomous-unapproved-write ---------------------------------------------

def test_autonomous_unapproved_write_fires():
    events = [
        _event("2026-07-13T11:00:00Z", action_type="session_start", actor_type="autonomous", tool=""),
        _event("2026-07-13T11:00:01Z", actor_type="autonomous", tool="vault_fs.write_file",
                tactic_id="TA0040", technique_id="T1565"),
    ]
    dets = run_detections(events)
    assert any(d.rule_id == "autonomous-unapproved-write" and d.severity == "high" for d in dets)


def test_autonomous_write_after_approval_is_clean():
    events = [
        _event("2026-07-13T11:00:00Z", action_type="approval_response", outcome="success", actor_type="human"),
        _event("2026-07-13T11:00:01Z", actor_type="autonomous", tool="vault_fs.write_file",
                tactic_id="TA0040", technique_id="T1565"),
    ]
    assert "autonomous-unapproved-write" not in _rule_ids(events)


def test_human_write_is_not_flagged():
    events = [
        _event("2026-07-13T11:00:01Z", actor_type="human", tool="vault_fs.write_file",
                tactic_id="TA0040", technique_id="T1565"),
    ]
    assert "autonomous-unapproved-write" not in _rule_ids(events)


# --- discovery-then-collect --------------------------------------------------

def test_discovery_then_collect_fires():
    events = [
        _event("2026-07-13T12:00:00Z", tool="vault_fs.list_dir", tactic_id="TA0007", technique_id="T1083"),
        _event("2026-07-13T12:00:01Z", tool="vault_fs.list_dir", tactic_id="TA0007", technique_id="T1083"),
        _event("2026-07-13T12:00:02Z", tool="vault_fs.glob", tactic_id="TA0007", technique_id="T1083"),
        _event("2026-07-13T12:00:03Z", tool="vault_fs.read_file", tactic_id="TA0009", technique_id="T1005"),
    ]
    dets = run_detections(events)
    d = next(d for d in dets if d.rule_id == "discovery-then-collect")
    assert d.severity == "medium"
    assert len(d.event_ids) == 4


def test_discovery_below_threshold_is_clean():
    events = [
        _event("2026-07-13T12:00:00Z", tool="vault_fs.list_dir", tactic_id="TA0007", technique_id="T1083"),
        _event("2026-07-13T12:00:03Z", tool="vault_fs.read_file", tactic_id="TA0009", technique_id="T1005"),
    ]
    assert "discovery-then-collect" not in _rule_ids(events)


# --- engine ------------------------------------------------------------------

def test_empty_session_returns_no_detections():
    assert run_detections([]) == []


def test_benign_session_returns_nothing():
    events = [
        _event("2026-07-13T09:00:00Z", action_type="session_start"),
        _event("2026-07-13T09:00:01Z", tool="vault_fs.read_file", tactic_id="TA0009", technique_id="T1005"),
        _event("2026-07-13T09:00:02Z", action_type="session_end"),
    ]
    assert run_detections(events) == []


def test_detections_ranked_most_severe_first():
    events = [
        # discovery-then-collect (medium)
        _event("2026-07-13T13:00:00Z", tool="fs.list_dir", tactic_id="TA0007", technique_id="T1083"),
        _event("2026-07-13T13:00:01Z", tool="fs.list_dir", tactic_id="TA0007", technique_id="T1083"),
        _event("2026-07-13T13:00:02Z", tool="fs.glob", tactic_id="TA0007", technique_id="T1083"),
        # credential-exfil (critical)
        _event("2026-07-13T13:00:03Z", tool="shell.cat", tactic_id="TA0006", technique_id="T1552.004"),
        _event("2026-07-13T13:00:04Z", tool="shell.curl", tactic_id="TA0011", technique_id="T1071.001"),
    ]
    dets = run_detections(events)
    assert dets[0].severity == "critical"
