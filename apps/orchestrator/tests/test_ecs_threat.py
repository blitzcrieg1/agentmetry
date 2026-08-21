"""ATT&CK classification has to reach the field a SOC actually queries.

Issue #46. The mapping in `core/audit/mitre.py` was correct and complete, and it
was landing only in `agentmetry.tool.mitre.*`, our own namespace. Elastic's
prebuilt content, ATT&CK Navigator coverage layers and every "techniques
observed" dashboard join on `threat.technique.id`. A customer forwarding into an
Elastic they already run saw nothing from us on any of them.

The other half of the contract is that `threat.*` carries ATT&CK and only
ATT&CK. ECS has `threat.framework` because the fieldset is not reserved to one
taxonomy, which is exactly why an ATLAS id landing here would corrupt any rollup
that groups by technique without filtering on framework first. See #47.
"""

from __future__ import annotations

from agentmetry.core.audit.adapters.ecs import canonical_to_ecs


def _tool_call(mitre: dict | None) -> dict:
    tool: dict = {"name": "Read", "qualified": "cursor.Read", "server": "cursor"}
    if mitre is not None:
        tool["mitre"] = mitre
    return {
        "schema_version": "1.1.0",
        "event_id": "e-1",
        "correlation_id": "conv-1",
        "timestamp_utc": "2026-08-21T09:14:22.041+00:00",
        "host_id": "dev-laptop",
        "action": {"type": "tool_called", "outcome": "success"},
        "actor": {"id": "dev_01", "role": "operator"},
        "tool": tool,
    }


CRED_ACCESS = {
    "tactic_id": "TA0006",
    "tactic": "Credential Access",
    "technique_id": "T1552.001",
    "technique": "Credentials In Files",
}


def test_tool_mitre_reaches_ecs_threat_fields():
    doc = canonical_to_ecs(_tool_call(CRED_ACCESS))

    assert doc["threat"] == {
        "framework": "MITRE ATT&CK",
        "tactic": {"id": "TA0006", "name": "Credential Access"},
        "technique": {"id": "T1552.001", "name": "Credentials In Files"},
    }


def test_vendor_namespace_is_unchanged():
    """The promotion is additive. Anything querying the old path keeps working."""
    doc = canonical_to_ecs(_tool_call(CRED_ACCESS))

    assert doc["agentmetry"]["tool"]["mitre"]["technique_id"] == "T1552.001"


def test_unclassified_call_has_no_threat_block():
    """`get_mitre_mapping` returns None rather than guessing.

    An adapter that filled the field anyway to make the document look complete
    would be undoing that decision on the way to the sink. Absent is the honest
    representation of "we did not classify this", and it is also what keeps a
    coverage dashboard from counting an unclassified call as covered.
    """
    doc = canonical_to_ecs(_tool_call(None))

    assert "threat" not in doc


def test_framework_alone_is_not_emitted():
    """A label with no technique under it is noise in every aggregation."""
    doc = canonical_to_ecs(_tool_call({}))

    assert "threat" not in doc


def test_partial_mapping_emits_only_what_is_known():
    doc = canonical_to_ecs(_tool_call({"tactic_id": "TA0002", "tactic": "Execution"}))

    assert doc["threat"] == {
        "framework": "MITRE ATT&CK",
        "tactic": {"id": "TA0002", "name": "Execution"},
    }
    assert "technique" not in doc["threat"]


def test_detection_carries_every_technique_that_produced_it():
    """A finding is the more useful thing to tag than one call underneath it.

    An analyst pivots from the alert. ECS keyword fields are multi-valued, so
    the id lists map straight across.
    """
    doc = canonical_to_ecs(
        {
            "schema_version": "1.1.0",
            "event_id": "e-2",
            "correlation_id": "conv-1",
            "timestamp_utc": "2026-08-21T09:20:00.000+00:00",
            "action": {"type": "detection", "outcome": "critical"},
            "detection": {
                "rule_id": "credential-exfil",
                "severity": "critical",
                "tactic_ids": ["TA0006", "TA0011"],
                "technique_ids": ["T1552.001", "T1071.001"],
            },
        }
    )

    assert doc["threat"] == {
        "framework": "MITRE ATT&CK",
        "tactic": {"id": ["TA0006", "TA0011"]},
        "technique": {"id": ["T1552.001", "T1071.001"]},
    }
    # The finding still files under the ECS category Elastic reserves for alerts.
    assert doc["event"]["category"] == ["intrusion_detection"]


def test_detection_without_techniques_has_no_threat_block():
    doc = canonical_to_ecs(
        {
            "event_id": "e-3",
            "timestamp_utc": "2026-08-21T09:20:00.000+00:00",
            "action": {"type": "detection", "outcome": "high"},
            "detection": {"rule_id": "session-tool-burst", "technique_ids": []},
        }
    )

    assert "threat" not in doc
