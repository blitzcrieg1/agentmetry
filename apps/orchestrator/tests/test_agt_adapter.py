"""Ingest Microsoft Agent Governance Toolkit audit files.

The fixtures are not hand-written. They were produced by the real
`FileAuditSink` from `agent-governance-toolkit-core` 5.0.0 in a throwaway venv,
and `AGT.verify_integrity()` returned True on them before they were copied here.
That matters: an adapter tested only against its own idea of the format is
testing that the author was consistent, not that the format is right.

Generating them is also how the verification algorithm was established. Their
docs describe the fields but not how the content hash is computed, and the
three details an external verifier needs -- the exact hashed field set, that
`previous_hash` chains to `content_hash` rather than to the signature, and that
the HMAC covers the hex string rather than the raw digest -- came from reading
`SignedAuditEntry._canonical_payload` and confirming against real output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmetry.core.audit.adapters.agt import (
    agt_file_to_canonical,
    agt_to_canonical,
    content_hash,
    read_agt_file,
    signature,
    verify_agt_chain,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXFIL = FIXTURES / "agt_filesink_exfil.jsonl"
MIXED = FIXTURES / "agt_filesink_mixed.jsonl"
KEY = b"scratch-key-not-a-secret"


# ----------------------------------------------------------------------
# Integrity, reproduced without their package
# ----------------------------------------------------------------------


def test_we_reproduce_their_hashes_with_stdlib_only():
    """No dependency on agent-governance-toolkit-core, which would pull 65
    transitive requirements into a tool whose pitch is that it runs locally
    without them."""
    rows = read_agt_file(EXFIL)
    assert len(rows) == 3
    for row in rows:
        assert content_hash(row) == row["content_hash"]
        assert signature(row["content_hash"], KEY) == row["signature"]


def test_the_chain_links_previous_hash_to_content_hash():
    """Not to the signature, which is the plausible wrong guess."""
    rows = read_agt_file(EXFIL)
    previous = ""
    for row in rows:
        assert row["previous_hash"] == previous
        previous = row["content_hash"]


def test_verification_passes_on_a_real_file():
    result = verify_agt_chain(read_agt_file(EXFIL), KEY)
    assert result.ok, result.message
    assert result.entries == 3
    assert result.signatures_checked


def test_hashes_and_chain_are_checkable_without_the_key():
    """The key is optional; editing and reordering are caught regardless. Only
    forgery by a key holder is out of reach, and that is out of reach for AGT
    too."""
    result = verify_agt_chain(read_agt_file(EXFIL), None)
    assert result.ok
    assert not result.signatures_checked


def test_an_edited_entry_is_caught(tmp_path):
    rows = read_agt_file(EXFIL)
    rows[1]["data"] = {"command": "echo harmless"}
    result = verify_agt_chain(rows, KEY)
    assert not result.ok
    assert 1 in result.hash_failures
    assert "index 1" in result.message


def test_a_reordered_file_is_caught():
    rows = read_agt_file(EXFIL)
    rows[1], rows[2] = rows[2], rows[1]
    result = verify_agt_chain(rows, KEY)
    assert not result.ok
    assert result.chain_failures


def test_a_removed_entry_is_caught():
    rows = read_agt_file(EXFIL)
    del rows[1]
    result = verify_agt_chain(rows, KEY)
    assert not result.ok
    assert result.chain_failures


def test_a_wrong_key_is_caught():
    result = verify_agt_chain(read_agt_file(EXFIL), b"not-the-key")
    assert not result.ok
    assert result.signature_failures


def test_an_unverifiable_file_yields_no_events(tmp_path):
    """The trail must not launder an unverified record. Appending it would have
    the hash chain vouch for a claim nobody checked, and the chain would be
    telling the truth about a lie."""
    bad = tmp_path / "tampered.jsonl"
    rows = read_agt_file(EXFIL)
    rows[0]["data"] = {"command": "rm -rf /"}
    bad.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    result, events = agt_file_to_canonical(bad, secret_key=KEY)
    assert not result.ok
    assert events == []


# ----------------------------------------------------------------------
# Mapping
# ----------------------------------------------------------------------


def test_agt_verdicts_map_onto_canonical_outcomes():
    rows = read_agt_file(MIXED)
    events = [agt_to_canonical(r) for r in rows]
    assert [e["action"]["type"] for e in events] == [
        "tool_called",
        "tool_denied",
        "tool_denied",
    ]
    assert [e["action"]["outcome"] for e in events] == ["success", "denied", "denied"]


def test_the_policy_rationale_survives():
    rows = read_agt_file(MIXED)
    event = agt_to_canonical(rows[1])
    assert "credential path denied" in event["action"]["reason"]
    assert "rule-no-creds" in event["action"]["reason"]


def test_mitre_and_traits_are_computed_not_carried():
    """AGT produces neither, and they are what lets the sequence rules see this
    activity at all. Adding them is the point of the adapter."""
    rows = read_agt_file(EXFIL)
    events = [agt_to_canonical(r) for r in rows]
    credential = events[1]
    assert credential["tool"]["mitre"]["technique_id"] == "T1552.001"
    assert "credential_access" in credential["tool"]["traits"]
    assert events[2]["tool"]["mitre"]["technique_id"] == "T1071.001"


def test_event_ids_are_stable_across_reimport():
    """AGT's entry_id is not a UUID, so it cannot be used directly. Deriving it
    deterministically stops a second import minting new identities for events
    already in the trail."""
    rows = read_agt_file(EXFIL)
    first = [agt_to_canonical(r)["event_id"] for r in rows]
    second = [agt_to_canonical(r)["event_id"] for r in rows]
    assert first == second
    assert len(set(first)) == 3


def test_custody_is_recorded_rather_than_implied():
    """Agentmetry did not observe these calls; it read someone else's record of
    them. A trail that cannot say so asserts more than it knows, which is the
    gap AGT's own maintainers concede in discussion #276.
    """
    event = agt_to_canonical(read_agt_file(EXFIL)[0])
    assert event["source"]["tier"] == "external"
    assert event["source"]["app"] == "agt"
    assert event["provenance"]["captured_by"] == "agent-governance-toolkit"
    assert event["provenance"]["agt_content_hash"]


# ----------------------------------------------------------------------
# The point of the whole thing
# ----------------------------------------------------------------------


def test_sequence_detection_fires_over_agt_events():
    """AGT allowed all three of these calls. Its policy engine evaluates one
    call at a time, so a credential read and a later egress are two permitted
    actions. Correlating them across the session is what this adapter buys.
    """
    from agentmetry.core.audit.detection.engine import run_detections

    result, events = agt_file_to_canonical(EXFIL, secret_key=KEY)
    assert result.ok
    assert all(e["action"]["outcome"] == "success" for e in events), (
        "AGT permitted every one of these calls"
    )

    detections = run_detections(events)
    rule_ids = {d.rule_id for d in detections}
    assert "credential-exfil" in rule_ids
    assert any(d.severity == "critical" for d in detections)


def test_an_empty_file_is_not_an_error(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    result, events = agt_file_to_canonical(empty)
    assert result.ok
    assert events == []


def test_non_agt_json_lines_are_ignored(tmp_path):
    mixed = tmp_path / "mixed.jsonl"
    lines = [json.dumps({"not": "an agt entry"}), "", "{ broken json"]
    lines += [line for line in EXFIL.read_text(encoding="utf-8").splitlines() if line.strip()]
    mixed.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = read_agt_file(mixed)
    assert len(rows) == 3


@pytest.mark.parametrize("field_name", ["content_hash", "previous_hash", "signature"])
def test_the_on_disk_format_is_signed_entry_not_audit_entry(field_name):
    """`AuditEntry` carries `entry_hash`; `SignedAuditEntry` is what reaches
    disk and carries these three instead. Reading one schema for the other is
    the easy mistake, so pin which one the adapter is written against."""
    row = read_agt_file(EXFIL)[0]
    assert field_name in row
    assert "entry_hash" not in row
