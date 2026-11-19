"""Read Microsoft Agent Governance Toolkit audit files into the canonical trail.

AGT governs agents you *build* -- Semantic Kernel, AutoGen, LangGraph, CrewAI --
and its `FileAuditSink` writes hash-chained, HMAC-signed JSONL. Agentmetry hooks
agents you *use*. Reading their file closes the gap between the two without
either project writing a framework integration, and it gives AGT-governed
activity the thing AGT does not do: sequence detection across a session, with
MITRE tagging, so a credential read and a later egress become one finding.

No dependency on their package. The integrity algorithm is reproduced here from
their `SignedAuditEntry`, and a round-trip against a file produced by the real
`FileAuditSink` 5.0.0 confirms it byte for byte. Depending on
`agent-governance-toolkit-core` would pull 65 transitive requirements into a
tool whose whole pitch is that it runs locally without them.

## What their file actually looks like

Their docs describe two different objects and it is easy to read one for the
other. `AuditEntry` is the in-memory record and carries `entry_hash`;
`SignedAuditEntry` is what `FileAuditSink` writes, and it carries
`content_hash`, `previous_hash` and `signature` instead. There is no
`entry_hash` on disk.

What no document states, and what an external verifier actually needs, had to
come from reading `SignedAuditEntry._canonical_payload`:

- The content hash covers exactly fourteen fields, serialised with
  `sort_keys=True` and `default=str`. `sandbox_id`, `environment` and
  `compute_driver` are deliberately excluded so they can be added without
  invalidating existing chains, and including them breaks every hash.
- `previous_hash` links to the previous entry's **`content_hash`** -- not its
  signature, which is the plausible wrong guess.
- `signature` is HMAC-SHA256 over the **hex string** of the content hash, not
  over its raw bytes.

Also minor: `entry_id` is documented as a UUID and is in fact
`audit_<first 16 hex of a uuid4>`, so it will not parse as one.

All of this was established by generating a real file and reproducing its
hashes, not by reading the reference.

## Custody

Ingested events are marked `source.tier = "external"` and `source.app = "agt"`,
and they carry `provenance.captured_by = "agent-governance-toolkit"`. This is
not decoration. Agentmetry did not observe these tool calls; it read someone
else's record of them, and a trail that cannot tell the difference is making a
claim it has no basis for. AGT's own maintainers concede the same gap in
discussion #276: a sealed record does not prove faithful capture. Keeping the
distinction visible is the least we can do about it here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Fields covered by AGT's content hash, in their order-independent canonical
#: payload. `sandbox_id`, `environment` and `compute_driver` are deliberately
#: excluded by AGT so they can be added without invalidating existing chains;
#: excluding them here too is what makes the hashes reproduce.
_HASHED_FIELDS = (
    "entry_id",
    "timestamp",
    "event_type",
    "agent_did",
    "action",
    "resource",
    "target_did",
    "data",
    "outcome",
    "policy_decision",
    "matched_rule",
    "trace_id",
    "session_id",
    "previous_hash",
)

#: AGT event_type -> Agentmetry action.type.
_ACTION_TYPE = {
    "tool_invocation": "tool_called",
    "tool_blocked": "tool_denied",
    "policy_evaluation": "policy_evaluation",
    "approval_decision": "approval_decision",
    "policy_violation": "tool_denied",
    "rogue_detection": "detection",
    "agent_invocation": "session_start",
}

_DECISION_TYPES = {"policy_evaluation", "approval_decision"}


def content_hash(entry: dict[str, Any]) -> str:
    """Recompute AGT's SHA-256 content hash for one entry."""
    payload = {key: entry.get(key) for key in _HASHED_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def signature(content_hash_hex: str, secret_key: bytes) -> str:
    """HMAC-SHA256 over the *hex string* of the content hash, as AGT does it."""
    return hmac.new(secret_key, content_hash_hex.encode(), hashlib.sha256).hexdigest()


@dataclass
class AgtVerifyResult:
    ok: bool
    message: str
    entries: int = 0
    hash_failures: list[int] = field(default_factory=list)
    chain_failures: list[int] = field(default_factory=list)
    signature_failures: list[int] = field(default_factory=list)
    signatures_checked: bool = False


def read_agt_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and "content_hash" in record:
                rows.append(record)
    return rows


def verify_agt_chain(
    rows: list[dict[str, Any]], secret_key: bytes | None = None
) -> AgtVerifyResult:
    """Check content hashes, chain linkage and (with a key) HMAC signatures.

    Without a trusted key this checks internal consistency. Verification
    covers the supplied file and cannot establish capture completeness or
    continuity across rotated files.
    """
    if not rows:
        return AgtVerifyResult(ok=True, message="no AGT entries found", entries=0)

    hash_failures: list[int] = []
    chain_failures: list[int] = []
    signature_failures: list[int] = []
    previous = ""

    for index, row in enumerate(rows):
        if content_hash(row) != str(row.get("content_hash") or ""):
            hash_failures.append(index)
        if str(row.get("previous_hash") or "") != previous:
            chain_failures.append(index)
        if secret_key is not None:
            expected = signature(str(row.get("content_hash") or ""), secret_key)
            if not hmac.compare_digest(expected, str(row.get("signature") or "")):
                signature_failures.append(index)
        previous = str(row.get("content_hash") or "")

    problems = []
    if hash_failures:
        problems.append(f"{len(hash_failures)} content hash mismatch(es)")
    if chain_failures:
        problems.append(f"{len(chain_failures)} broken chain link(s)")
    if signature_failures:
        problems.append(f"{len(signature_failures)} bad signature(s)")

    if problems:
        first = min(
            [i for group in (hash_failures, chain_failures, signature_failures) for i in group]
        )
        return AgtVerifyResult(
            ok=False,
            message=f"{', '.join(problems)}; first bad entry at index {first}",
            entries=len(rows),
            hash_failures=hash_failures,
            chain_failures=chain_failures,
            signature_failures=signature_failures,
            signatures_checked=secret_key is not None,
        )

    checked = "chain consistent and HMAC verified" if secret_key is not None else "chain consistent"
    return AgtVerifyResult(
        ok=True,
        message=f"{len(rows)} AGT entries checked ({checked})",
        entries=len(rows),
        signatures_checked=secret_key is not None,
    )


def _tool_evidence(resource: str, data: dict[str, Any]) -> dict[str, Any]:
    from agentmetry.core.audit.detection.traits import classify_tool_call
    from agentmetry.core.audit.atlas import attach_atlas
    from agentmetry.core.audit.mitre import get_mitre_mapping

    command = str(data.get("command") or "")
    tool: dict[str, Any] = {
        "name": resource.rsplit(".", 1)[-1] if resource else "",
        "qualified": resource,
        "server": resource.split(".", 1)[0] if "." in resource else "agt",
        "arguments": data,
        "parameters_redacted": False,
    }
    if command:
        tool["command"] = command
        from agentmetry.core.audit.hashing import fingerprint

        tool["input_hash"], kind = fingerprint(command)
        tool["input_redaction"] = f"{kind}+command"
        traits = classify_tool_call(resource, command)
        if traits:
            tool["traits"] = traits
    mapping = get_mitre_mapping(resource or "run", data or command)
    if mapping:
        tool["mitre"] = mapping
    attach_atlas(tool)
    return tool


def agt_to_canonical(
    entry: dict[str, Any], *,
    host_id: str = "", fleet_id: str = "", verification: AgtVerifyResult | None = None,
) -> dict[str, Any]:
    """Map one source record and carry the verification actually performed."""
    from agentmetry.core.audit.canonical import SCHEMA_VERSION

    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    resource = str(entry.get("resource") or "")
    event_type = str(entry.get("event_type") or "")
    action_type = _ACTION_TYPE.get(event_type, "agt_event")
    source_action = str(entry.get("action") or "")
    outcome = str(entry.get("outcome") or "")
    verdict = source_action
    reason = entry.get("policy_decision")
    matched_rule = entry.get("matched_rule")
    if action_type in _DECISION_TYPES:
        # The wrapper records the requested action in "action". The approval
        # response and resolved evaluation are separate source observations.
        if action_type == "policy_evaluation":
            outcome = str(entry.get("policy_decision") or outcome)
        verdict = outcome
        reason = data.get("reason")
        matched_rule = matched_rule or data.get("rule")
    default_outcome = "denied" if action_type == "tool_denied" else "unknown"
    reason_parts = [str(p) for p in (reason, matched_rule) if p]

    agent_did = str(entry.get("agent_did") or "")
    chain_consistent = bool(verification and verification.ok and verification.entries)
    signatures_checked = bool(chain_consistent and verification and verification.signatures_checked)

    event = {
        "schema_version": SCHEMA_VERSION,
        # AGT's entry_id is `audit_<16 hex>`, not a UUID, so it cannot be used
        # as an event_id directly. Derived deterministically so re-importing the
        # same file does not mint new identities for the same events.
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"agt:{entry.get('entry_id')}")),
        "correlation_id": str(entry.get("trace_id") or entry.get("session_id") or ""),
        "session_id": str(entry.get("session_id") or ""),
        "timestamp_utc": str(entry.get("timestamp") or ""),
        "host_id": host_id,
        "fleet_id": fleet_id,
        "source_topic": f"external/agt/{action_type}",
        "source": {"tier": "external", "app": "agt", "adapter": "agt_file"},
        "actor": {"type": "agent", "id": agent_did, "role": "agent"},
        "initiator": {"actor_type": "agent", "trigger": "agt", "operator_id": agent_did},
        "action": {
            "type": action_type,
            "outcome": outcome or default_outcome,
            "reason": "; ".join(reason_parts),
        },
        "agent": {"name": agent_did or "agt", "skill_id": ""},
        "model": {"id": "", "provider": ""},
        "provenance": {
            "captured_by": "agent-governance-toolkit",
            "agt_entry_id": entry.get("entry_id"),
            "agt_content_hash": entry.get("content_hash"),
            "agt_previous_hash": entry.get("previous_hash"),
            "agt_event_type": event_type,
            "agt_action": source_action,
            "agt_verdict": verdict,
            "chain_consistent": chain_consistent,
            "signatures_checked": signatures_checked,
            "verified_on_import": signatures_checked,
        },
    }
    if action_type not in _DECISION_TYPES and action_type != "agt_event":
        event["tool"] = _tool_evidence(resource, data)
    return event


def agt_file_to_canonical(
    path: Path,
    *,
    secret_key: bytes | None = None,
    host_id: str = "",
    fleet_id: str = "",
) -> tuple[AgtVerifyResult, list[dict[str, Any]]]:
    """Verify an AGT file, then map it. Returns no events if verification fails."""
    rows = read_agt_file(path)
    result = verify_agt_chain(rows, secret_key)
    if not result.ok:
        return result, []
    events = [
        agt_to_canonical(row, host_id=host_id, fleet_id=fleet_id, verification=result)
        for row in rows
    ]
    return result, events
