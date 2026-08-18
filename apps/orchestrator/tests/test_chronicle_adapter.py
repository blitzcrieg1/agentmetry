"""Chronicle UDM mapping.

Two failure modes shape this file, and only one of them is visible in testing
without a Chronicle tenant.

The first is ingest rejection. `metadata.event_type` decides which UDM fields
Chronicle *requires*, so a mis-declared type is refused at the door rather than
stored imperfectly. That failure is loud in the tenant and silent here: the
adapter returns a dict, every test passes, and the events never arrive.
`test_no_event_ships_without_a_target` and the event-type tests exist for that.

The second is overstatement. Mapping a tool call that reads a file to FILE_READ
would make an agent's *intent* to read indistinguishable from the kernel's record
of a read, in a SIEM whose whole job is telling evidence apart.
"""

from __future__ import annotations

import json

import pytest

from agentmetry.core.audit.adapters.chronicle import (
    canonical_to_udm,
    canonical_to_udm_batch,
    udm_event_type,
)

#: UDM types that Chronicle will not accept without a target entity.
_TARGET_REQUIRED = {"USER_RESOURCE_ACCESS", "PROCESS_LAUNCH", "FILE_READ", "NETWORK_HTTP"}


def _event(**over):
    base = {
        "schema_version": "1.1.0",
        "event_id": "evt-1",
        "timestamp_utc": "2026-08-18T12:00:00+00:00",
        "host_id": "DEV-01",
        "fleet_id": "acme",
        "correlation_id": "sess-1",
        "actor": {"id": "ioannis"},
        "agent": {"name": "claude"},
        "source": {"app": "claude"},
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
        "tool": {"qualified": "Bash", "command": "ls -la"},
    }
    base.update(over)
    return base


# ----------------------------------------------------------------------
# The ingest-rejection class
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        _event(),
        _event(action={"type": "detection", "outcome": "critical", "reason": "x"},
               detection={"rule_id": "credential-exfil", "severity": "critical", "summary": "s"},
               tool=None),
        _event(action={"type": "session_start", "outcome": "success"}, tool=None,
               correlation_id="", session_id=""),
        _event(action={"type": "tool_denied", "outcome": "denied", "reason": "policy"},
               tool={"qualified": "cursor.Delete"}),
    ],
)
def test_no_event_ships_without_a_target(event):
    """An empty target is not cosmetic, it is a rejected event.

    A detection carries no tool because it is a finding about a session rather
    than about one call, so the naive mapping drops target entirely. Everything
    upstream then reports success while the SIEM never receives the finding,
    which is the worst available failure for an audit product.
    """
    udm = canonical_to_udm(event)
    if udm["metadata"]["event_type"] in _TARGET_REQUIRED:
        assert udm.get("target"), udm["metadata"]["event_type"]


def test_every_event_has_a_principal_and_a_timestamp():
    udm = canonical_to_udm(_event())
    assert udm["principal"]["hostname"] == "DEV-01"
    assert udm["metadata"]["event_timestamp"].endswith("Z")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-18T12:00:00+00:00", "2026-08-18T12:00:00Z"),
        ("2026-08-18T12:00:00Z", "2026-08-18T12:00:00Z"),
        ("2026-08-18T14:00:00+02:00", "2026-08-18T12:00:00Z"),
    ],
)
def test_timestamps_normalise_to_rfc3339_zulu(raw, expected):
    assert canonical_to_udm(_event(timestamp_utc=raw))["metadata"]["event_timestamp"] == expected


def test_an_unparseable_timestamp_does_not_drop_the_event(monkeypatch):
    """A broken clock should cost the timestamp, not the record."""
    udm = canonical_to_udm(_event(timestamp_utc="yesterday-ish"))
    assert udm["metadata"]["event_timestamp"].endswith("Z")


# ----------------------------------------------------------------------
# Event types, conservatively
# ----------------------------------------------------------------------


def test_a_shell_tool_call_is_a_process_launch():
    assert udm_event_type(_event()) == "PROCESS_LAUNCH"
    assert canonical_to_udm(_event())["target"]["process"]["command_line"] == "ls -la"


def test_a_shell_tool_with_no_command_is_not_a_process_launch():
    """PROCESS_LAUNCH without a process is rejected by Chronicle."""
    assert udm_event_type(_event(tool={"qualified": "Bash"})) == "USER_RESOURCE_ACCESS"


def test_a_file_read_is_not_claimed_as_FILE_READ():
    """Agentmetry sees the agent's intent to read, not the kernel's record of a
    read. Claiming the stronger type makes the two indistinguishable in a search
    whose entire purpose is telling evidence apart."""
    udm = canonical_to_udm(_event(tool={"qualified": "cursor.Read", "command": ""}))
    assert udm["metadata"]["event_type"] == "USER_RESOURCE_ACCESS"


def test_a_heartbeat_is_a_status_update():
    """The native UDM type for endpoint status reporting, so the silence rule is
    an absence check over a standard type rather than a vendor-specific one."""
    assert udm_event_type(_event(action={"type": "heartbeat", "outcome": "success"})) == "STATUS_UPDATE"


def test_an_mcp_schema_observation_is_a_status_update():
    """It is configuration attestation, the same family as a heartbeat, not a
    process launch and not an alert."""
    assert udm_event_type(_event(action={"type": "mcp_schema", "outcome": "changed"})) == "STATUS_UPDATE"


def test_an_unknown_action_type_still_maps():
    """A new canonical action must not become an unroutable event."""
    assert udm_event_type(_event(action={"type": "something_new"})) == "USER_RESOURCE_ACCESS"


# ----------------------------------------------------------------------
# security_result, which is what Chronicle alerts on
# ----------------------------------------------------------------------


def test_a_detection_alerts_with_chronicle_native_severity():
    """A customer writes YARA-L against security_result.severity without ever
    learning what a detection.rule_id is."""
    udm = canonical_to_udm(_event(
        action={"type": "detection", "outcome": "critical", "reason": "cred then egress"},
        detection={"rule_id": "credential-exfil", "title": "Credential exfiltration",
                   "severity": "critical", "summary": "Read a key then egressed.",
                   "technique_ids": ["T1552.004", "T1071.001"]},
        tool=None,
    ))
    result = udm["security_result"][0]
    assert result["alert_state"] == "ALERTING"
    assert result["severity"] == "CRITICAL"
    assert result["rule_id"] == "credential-exfil"
    assert "T1552.004" in result["category_details"]


@pytest.mark.parametrize(
    "severity,expected",
    [("critical", "CRITICAL"), ("high", "HIGH"), ("medium", "MEDIUM"),
     ("low", "LOW"), ("wat", "INFORMATIONAL")],
)
def test_severity_maps_and_never_drops(severity, expected):
    """An unmapped severity becomes INFORMATIONAL rather than vanishing. A
    finding nobody can search for is worse than a mislabelled one."""
    udm = canonical_to_udm(_event(
        action={"type": "detection", "outcome": severity},
        detection={"rule_id": "r", "severity": severity, "summary": "s"}, tool=None,
    ))
    assert udm["security_result"][0]["severity"] == expected


def test_a_denied_tool_call_is_a_block():
    udm = canonical_to_udm(_event(
        action={"type": "tool_denied", "outcome": "denied", "reason": "policy said no"},
        tool={"qualified": "cursor.Delete"},
    ))
    assert udm["security_result"][0]["action"] == ["BLOCK"]


def test_a_degraded_heartbeat_alerts():
    """The tamper signal has to arrive as an alert, not as a status line nobody
    reads."""
    udm = canonical_to_udm(_event(
        action={"type": "heartbeat", "outcome": "degraded", "reason": "hooks NOT installed for: cursor"},
        tool=None,
    ))
    result = udm["security_result"][0]
    assert result["alert_state"] == "ALERTING"
    assert "cursor" in result["summary"]


def test_a_healthy_heartbeat_does_not_alert():
    udm = canonical_to_udm(_event(action={"type": "heartbeat", "outcome": "success"}, tool=None))
    assert "security_result" not in udm


# ----------------------------------------------------------------------
# Pivotability and hygiene
# ----------------------------------------------------------------------


def test_correlation_id_survives_as_a_searchable_label():
    """It is how a responder pivots from one finding to the whole session. Buried
    in a JSON blob it is not a pivot, it is a string."""
    labels = canonical_to_udm(_event())["additional"]["labels"]
    assert {"key": "correlation_id", "value": "sess-1"} in labels


def test_a_very_long_command_is_truncated():
    """A UDM string field is not a log body, and a 100KB heredoc in a search
    result helps nobody."""
    udm = canonical_to_udm(_event(tool={"qualified": "Bash", "command": "x" * 50_000}))
    assert len(udm["target"]["process"]["command_line"]) == 4000


def test_empty_sections_are_omitted_not_sent_as_nulls():
    udm = canonical_to_udm({"event_id": "e", "action": {"type": "session_start"}})
    assert all(v for v in udm.values())
    assert "null" not in json.dumps(udm)


def test_the_batch_body_is_the_udmevents_shape():
    body = canonical_to_udm_batch([_event(), _event()], customer_id="cust-123")
    assert body["customer_id"] == "cust-123"
    assert len(body["events"]) == 2
    assert body["events"][0]["metadata"]["vendor_name"] == "Agentmetry"


def test_customer_id_is_omitted_when_unset():
    assert "customer_id" not in canonical_to_udm_batch([_event()])
