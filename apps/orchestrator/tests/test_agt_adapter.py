"""Ingest Microsoft Agent Governance Toolkit audit files.

The original fixtures were produced by the real `FileAuditSink` from
`agent-governance-toolkit-core` 5.0.0. The `agt_govern_*` fixtures come from
the upstream version reviewed in discussion #4560. See
`fixtures/generate_agt_govern.py` for their capture script.
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
GOVERN_KEY = b"agentmetry-synthetic-agt-fixture-key"
GOVERN_DECISIONS = FIXTURES / "agt_govern_decisions.jsonl"


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
    result, events = agt_file_to_canonical(EXFIL)
    assert result.ok
    assert not result.signatures_checked
    assert "chain consistent" in result.message
    for event in events:
        provenance = event["provenance"]
        assert provenance["chain_consistent"] is True
        assert provenance["signatures_checked"] is False
        assert provenance["verified_on_import"] is False


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
    result, events = agt_file_to_canonical(EXFIL, secret_key=b"not-the-key")
    assert not result.ok
    assert result.signature_failures
    assert events == []


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
    assert event["provenance"]["chain_consistent"] is False
    assert event["provenance"]["signatures_checked"] is False
    assert event["provenance"]["verified_on_import"] is False


def test_govern_records_decisions_without_tool_evidence():
    from agentmetry.core.audit.detection.engine import run_detections

    result, events = agt_file_to_canonical(GOVERN_DECISIONS, secret_key=GOVERN_KEY)
    assert result.ok and result.signatures_checked
    assert "HMAC verified" in result.message
    assert [event["action"]["type"] for event in events] == ["policy_evaluation"] * 2
    assert [event["action"]["outcome"] for event in events] == ["allow", "deny"]
    assert "fixture-rule" in events[1]["action"]["reason"]
    assert [event["provenance"]["agt_action"] for event in events] == ["read", "write"]
    assert [event["provenance"]["agt_verdict"] for event in events] == ["allow", "deny"]
    rows = read_agt_file(GOVERN_DECISIONS)
    assert [event["provenance"]["agt_entry_id"] for event in events] == [
        row["entry_id"] for row in rows
    ]
    assert all("tool" not in event for event in events)
    for event in events:
        provenance = event["provenance"]
        assert provenance["chain_consistent"] is True
        assert provenance["signatures_checked"] is True
        assert provenance["verified_on_import"] is True
    assert run_detections(events) == []


def test_approval_and_resolved_evaluation_are_distinct_records():
    path = FIXTURES / "agt_govern_approval.jsonl"
    result, events = agt_file_to_canonical(path, secret_key=GOVERN_KEY)
    assert result.ok
    assert [event["action"]["type"] for event in events] == [
        "approval_decision", "policy_evaluation",
    ]
    assert [event["action"]["outcome"] for event in events] == ["rejected", "deny"]
    assert "Synthetic approval rejected" in events[0]["action"]["reason"]
    assert all("tool" not in event for event in events)
    assert len({event["event_id"] for event in events}) == 2


def test_rotated_files_are_independent_chains():
    files = [FIXTURES / f"agt_govern_rotation_{suffix}.jsonl" for suffix in ("first", "second")]
    for path in files:
        result, events = agt_file_to_canonical(path, secret_key=GOVERN_KEY)
        assert result.ok and result.signatures_checked
        (event,) = events
        assert event["provenance"]["agt_previous_hash"] == ""
    result = verify_agt_chain(read_agt_file(files[0]) + read_agt_file(files[1]), GOVERN_KEY)
    assert not result.ok
    assert result.chain_failures == [1]
    assert result.signature_failures == []


def test_legacy_allow_without_a_tool_result_stays_unknown():
    row = {**read_agt_file(EXFIL)[0], "outcome": ""}
    event = agt_to_canonical(row)
    assert event["action"]["type"] == "tool_called"
    assert event["action"]["outcome"] == "unknown"
    assert event["provenance"]["agt_verdict"] == "allow"


def test_unknown_source_kind_does_not_become_a_tool_call():
    row = {**read_agt_file(EXFIL)[0], "event_type": "tool_called"}
    event = agt_to_canonical(row)
    assert event["action"]["type"] == "agt_event"
    assert event["provenance"]["agt_event_type"] == "tool_called"
    assert "tool" not in event


def test_cli_dry_run_distinguishes_chain_check_from_hmac(monkeypatch, capsys):
    from agentmetry.cli import main

    monkeypatch.delenv("AGENTMETRY_AGT_HMAC_KEY", raising=False)
    args = ["import-agt", str(GOVERN_DECISIONS), "--dry-run"]
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "chain consistent" in output
    assert "Source authenticity unverified" in output
    assert "2 event(s) would be appended" in output

    monkeypatch.setenv("AGENTMETRY_AGT_HMAC_KEY", GOVERN_KEY.decode())
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "chain consistent and HMAC verified" in output
    assert "Source authenticity unverified" not in output


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
