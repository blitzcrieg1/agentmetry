"""CloudEvents v1.0 envelope mapping.

The tests that matter are the spec-conformance ones. An envelope that is
slightly wrong is worse than no adapter: it is accepted by a permissive broker,
rejected by a strict one, and the difference shows up as events that silently
stop arriving at one subscriber.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

import pytest

from agentmetry.core.audit.adapters.cloudevents import (
    CE_SPECVERSION,
    canonical_to_cloudevent,
    canonical_to_cloudevents,
    cloudevent_type,
    extension_attributes,
)


def _event(**overrides):
    base = {
        "schema_version": "1.1.0",
        "event_id": "6a8ef924-d4ba-4f3d-896d-e62bacc3150a",
        "correlation_id": "corr-1",
        "session_id": "sess-1",
        "fleet_id": "acme-eng",
        "host_id": "WORKSTATION-01",
        "timestamp_utc": "2026-08-06T10:00:00+00:00",
        "source": {"tier": "external", "app": "claude"},
        "action": {"type": "tool_called", "outcome": "success"},
        "tool": {"name": "Bash", "qualified": "shell.run"},
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# Required attributes (CloudEvents 1.0 §3.1)
# ----------------------------------------------------------------------


def test_required_attributes_are_present_and_non_empty():
    ce = canonical_to_cloudevent(_event())
    for attr in ("specversion", "id", "source", "type"):
        assert attr in ce, f"{attr} is REQUIRED"
        assert isinstance(ce[attr], str) and ce[attr], f"{attr} must be a non-empty string"
    assert ce["specversion"] == CE_SPECVERSION


def test_no_attribute_is_ever_an_empty_string():
    """CloudEvents forbids empty-string attribute values, so absent fields must
    be omitted rather than blanked. A canonical event with almost nothing in it
    is the case that catches this."""
    sparse = {"event_id": "e1", "action": {"type": "session_start"}}
    ce = canonical_to_cloudevent(sparse)
    for key, value in ce.items():
        if key == "data":
            continue
        assert value != "", f"{key} is an empty string"


def test_source_survives_a_missing_host():
    """`source` is REQUIRED and non-empty. Falling back beats emitting an
    envelope a strict consumer rejects."""
    ce = canonical_to_cloudevent({"event_id": "e1", "action": {"type": "tool_called"}})
    assert ce["source"].startswith("/agentmetry/")
    assert "unknown-host" in ce["source"]


def test_time_is_rfc3339_with_a_z():
    ce = canonical_to_cloudevent(_event())
    assert ce["time"] == "2026-08-06T10:00:00Z"
    datetime.fromisoformat(ce["time"].replace("Z", "+00:00"))


def test_time_is_generated_when_the_event_has_none():
    ce = canonical_to_cloudevent({"event_id": "e1", "action": {"type": "tool_called"}})
    datetime.fromisoformat(ce["time"].replace("Z", "+00:00"))


# ----------------------------------------------------------------------
# Extension attribute naming (§3.1, "Attribute Naming Convention")
# ----------------------------------------------------------------------


_VALID_NAME = re.compile(r"^[a-z0-9]+$")


@pytest.mark.parametrize(
    "canonical",
    [
        _event(),
        _event(action={"type": "detection", "outcome": "critical"},
               detection={"rule_id": "credential-exfil", "severity": "critical"}),
        _event(action={"type": "tool_denied", "outcome": "denied"}),
    ],
)
def test_extension_names_are_lowercase_alphanumeric_and_short(canonical):
    """Two rules, both easy to violate by copying an example.

    Names must be `[a-z0-9]` only, so no underscores and no dots; and they
    SHOULD NOT exceed 20 characters, which appears in the prose and in none of
    the examples. `agentmetrycorrelationid` is 23 and had to become
    `agentmetrycorrid`.
    """
    for name in extension_attributes(canonical_to_cloudevent(canonical)):
        assert _VALID_NAME.match(name), f"{name!r} is not lowercase alphanumeric"
        assert len(name) <= 20, f"{name!r} is {len(name)} characters, over the 20 limit"


def test_extensions_carry_what_a_router_filters_on():
    ce = canonical_to_cloudevent(
        _event(
            action={"type": "detection", "outcome": "critical"},
            detection={"rule_id": "credential-exfil", "severity": "critical"},
        )
    )
    assert ce["agentmetryseverity"] == "critical"
    assert ce["agentmetryrule"] == "credential-exfil"
    assert ce["agentmetrycorrid"] == "corr-1"


def test_absent_extensions_are_omitted_not_null():
    ce = canonical_to_cloudevent(_event())
    assert "agentmetryseverity" not in ce, "a tool call has no severity"
    assert "agentmetryrule" not in ce


# ----------------------------------------------------------------------
# Types and subject
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action_type", "expected"),
    [
        ("tool_called", "ai.agentmetry.tool.called"),
        ("detection", "ai.agentmetry.detection.raised"),
        ("detection_disposition", "ai.agentmetry.detection.dispositioned"),
        ("approval_request", "ai.agentmetry.approval.requested"),
        ("session_start", "ai.agentmetry.session.started"),
    ],
)
def test_known_types_map_to_reverse_dns(action_type, expected):
    assert cloudevent_type(action_type) == expected


def test_an_unmapped_action_still_gets_a_well_formed_type():
    """A new action type must not silently stop being forwarded. Falling back
    beats returning None, which is how a recorder goes quiet."""
    assert cloudevent_type("brand_new_thing") == "ai.agentmetry.brand.new.thing"
    assert cloudevent_type("") == "ai.agentmetry.unknown"


def test_subject_is_what_the_event_is_about():
    tool = canonical_to_cloudevent(_event())
    assert tool["subject"] == "shell.run"
    det = canonical_to_cloudevent(
        _event(action={"type": "detection"}, detection={"rule_id": "credential-exfil"})
    )
    assert det["subject"] == "credential-exfil"


def test_subject_is_omitted_when_there_is_nothing_to_name():
    ce = canonical_to_cloudevent({"event_id": "e1", "action": {"type": "session_start"}})
    assert "subject" not in ce


# ----------------------------------------------------------------------
# The payload
# ----------------------------------------------------------------------


def test_the_canonical_event_travels_whole():
    """Flattening would mean a second field list that drifts, and would drop the
    chain fields, the MITRE tagging and the traits -- the parts that make the
    record worth forwarding at all."""
    canonical = _event(
        tool={
            "name": "Bash",
            "qualified": "shell.run",
            "traits": ["credential_access"],
            "mitre": {"technique_id": "T1552.001", "tactic_id": "TA0006"},
        }
    )
    ce = canonical_to_cloudevent(canonical)
    assert ce["data"] == canonical
    assert ce["data"]["tool"]["mitre"]["technique_id"] == "T1552.001"
    assert ce["data"]["tool"]["traits"] == ["credential_access"]


def test_the_envelope_is_json_serialisable():
    ce = canonical_to_cloudevent(_event())
    assert json.loads(json.dumps(ce)) == ce


def test_batch_mapping():
    events = [_event(), _event(action={"type": "session_end"})]
    out = canonical_to_cloudevents(events)
    assert [e["type"] for e in out] == [
        "ai.agentmetry.tool.called",
        "ai.agentmetry.session.ended",
    ]


# ----------------------------------------------------------------------
# Sink wiring
# ----------------------------------------------------------------------


def test_the_webhook_default_shape_is_unchanged():
    """An option appearing must not change what an existing webhook receives."""
    from agentmetry.core.audit.sinks import WebhookAuditSink

    assert WebhookAuditSink("https://example.invalid/h")._cloudevents is False
    assert WebhookAuditSink("https://example.invalid/h", format="cloudevents")._cloudevents


@pytest.mark.parametrize("spelling", ["cloudevents", "CloudEvents", " ce ", "cloudevent"])
def test_format_spellings_people_actually_type(spelling):
    from agentmetry.core.audit.sinks import WebhookAuditSink

    assert WebhookAuditSink("https://example.invalid/h", format=spelling)._cloudevents
