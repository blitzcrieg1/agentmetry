"""ATLAS labels the half of the threat model ATT&CK has no id for.

Issue #47. `mitre.py` maps ten ATT&CK techniques and every one of them describes
host behaviour that happens to be performed through an agent. That is correct
for those events and says nothing about the three capabilities that most
distinguish this product: an MCP server swapping its advertised tool schema, a
prompt-injection carrier, and an agent present but unrecorded.

These tests hold the two properties the module exists for. It stays empty unless
ATLAS adds a claim ATT&CK cannot make, and it never reaches ECS `threat.*`,
where an `AML.T****` would corrupt customer rollups that group by technique
without checking the framework.

Ids verified against ATLAS 2026.07 format-version 6.0.0. The widely-linked
dist/ATLAS.yaml is a deprecated 5.6.0 snapshot; these came from dist/v6.
"""

from __future__ import annotations

from agentmetry.core.audit.adapters.ecs import canonical_to_ecs
from agentmetry.core.audit.atlas import (
    ATLAS_FRAMEWORK,
    RUG_PULL,
    attach_atlas,
    get_atlas_mapping,
)
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.ingest import build_schema_canonical


def _mitre(technique_id: str) -> dict:
    return {"tactic_id": "TA0006", "tactic": "x", "technique_id": technique_id, "technique": "y"}


def test_credential_read_is_agent_tool_credential_harvesting():
    m = get_atlas_mapping(_mitre("T1552.001"))
    assert m["technique_id"] == "AML.T0098"
    assert m["technique"] == "AI Agent Tool Credential Harvesting"
    assert m["tactic_id"] == "AML.TA0013"
    assert m["framework"] == ATLAS_FRAMEWORK


def test_private_key_read_maps_to_the_same_technique():
    assert get_atlas_mapping(_mitre("T1552.004"))["technique_id"] == "AML.T0098"


def test_egress_is_exfiltration_via_agent_tool_invocation():
    m = get_atlas_mapping(_mitre("T1071.001"))
    assert m["technique_id"] == "AML.T0086"
    assert m["tactic_id"] == "AML.TA0010"


def test_destruction_is_data_destruction_via_agent_tool_invocation():
    m = get_atlas_mapping(_mitre("T1485"))
    assert m["technique_id"] == "AML.T0101"
    assert m["tactic_id"] == "AML.TA0011"


def test_shell_execution_gets_no_atlas_label():
    """AML.T0050 is ATLAS restating T1059 with no agent-specific claim.

    Emitting it would be the forced mapping this module exists to avoid, and
    would make the field look populated without carrying information.
    """
    assert get_atlas_mapping(_mitre("T1059.004")) is None


def test_ordinary_reads_and_discovery_get_no_atlas_label():
    assert get_atlas_mapping(_mitre("T1005")) is None
    assert get_atlas_mapping(_mitre("T1083")) is None


def test_unclassified_call_gets_nothing():
    assert get_atlas_mapping(None) is None
    assert get_atlas_mapping({}) is None
    assert get_atlas_mapping("not a mapping") is None


def test_attach_never_overwrites_what_an_adapter_asserted():
    """An adapter nearer the source knows more than a lookup table does."""
    theirs = {"framework": ATLAS_FRAMEWORK, "technique_id": "AML.T0110"}
    tool = {"mitre": _mitre("T1552.001"), "atlas": theirs}
    attach_atlas(tool)
    assert tool["atlas"] == theirs


def test_attach_is_a_noop_when_atlas_has_nothing_to_add():
    tool = {"mitre": _mitre("T1059.004")}
    attach_atlas(tool)
    assert "atlas" not in tool


def test_enrichment_reaches_a_real_external_event():
    event = build_external_canonical(
        {
            "source_app": "cursor",
            "event_type": "tool_called",
            "outcome": "success",
            "correlation_id": "c1",
            "tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"},
        }
    )
    assert event["tool"]["mitre"]["technique_id"] == "T1552.004"
    assert event["tool"]["atlas"]["technique_id"] == "AML.T0098"


def test_both_taxonomies_describe_the_same_event_without_contradicting():
    """The ATLAS block is derived from the ATT&CK block, not re-parsed.

    Two independent passes over the same evidence would eventually disagree
    about one event, and the disagreement would be invisible until somebody
    queried both.
    """
    event = build_external_canonical(
        {
            "source_app": "claude",
            "event_type": "tool_called",
            "outcome": "success",
            "correlation_id": "c2",
            "tool": {"qualified": "WebFetch", "command": "fetch https://example.com"},
        }
    )
    assert event["tool"]["mitre"]["technique_id"] == "T1071.001"
    assert event["tool"]["atlas"]["technique_id"] == "AML.T0086"


def test_a_moved_schema_is_the_rug_pull_technique():
    event = build_schema_canonical({"source_app": "mcp_proxy"}, "changed")
    assert event["mcp_schema"]["atlas"] == dict(RUG_PULL)
    assert event["mcp_schema"]["atlas"]["technique_id"] == "AML.T0109"
    # Defense Evasion, not Initial Access. Shipping clean releases first is the
    # point: scrutiny happens at adoption, not at update.
    assert event["mcp_schema"]["atlas"]["tactic_id"] == "AML.TA0007"


def test_a_first_sighting_or_a_quiet_reconnect_is_not_a_rug_pull():
    for status in ("new", "same"):
        event = build_schema_canonical({"source_app": "mcp_proxy"}, status)
        assert "atlas" not in event["mcp_schema"], status


def test_atlas_never_reaches_ecs_threat_fields():
    """`threat.*` is ATT&CK-typed. An AML id there poisons customer rollups.

    The vendor namespace carries it instead, which is where a consumer that
    wants it can find it without any aggregation over `threat.technique.id`
    silently mixing two taxonomies.
    """
    event = build_external_canonical(
        {
            "source_app": "cursor",
            "event_type": "tool_called",
            "outcome": "success",
            "correlation_id": "c3",
            "tool": {"qualified": "cursor.Read", "command": "cat ~/.aws/credentials"},
        }
    )
    doc = canonical_to_ecs(event)

    assert doc["threat"]["framework"] == "MITRE ATT&CK"
    assert doc["threat"]["technique"]["id"].startswith("T1")
    assert "AML" not in str(doc["threat"])
    # Still reachable, in the namespace that is ours to define.
    assert doc["agentmetry"]["tool"]["atlas"]["technique_id"] == "AML.T0098"
