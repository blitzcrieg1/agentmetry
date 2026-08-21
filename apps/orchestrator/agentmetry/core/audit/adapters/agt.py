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
    "policy_evaluation": "tool_called",
    "policy_violation": "tool_denied",
    "rogue_detection": "detection",
    "agent_invocation": "session_start",
}

#: AGT policy verdict -> Agentmetry action.outcome, when AGT's own `outcome`
#: is missing. AGT carries both a verdict (`action`) and a result (`outcome`);
#: Agentmetry has one field, and the result is the more factual of the two.
_OUTCOME = {
    "allow": "success",
    "deny": "denied",
    "quarantine": "denied",
    "warning": "success",
    "audit": "success",
}


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

    Verified before ingest, never after. Importing someone else's audit record
    into a hash-chained trail without checking it first would launder an
    unverified claim into a chain that then vouches for it, and the chain would
    be telling the truth about a lie.

    The signature is optional because the key is optional. Without it the
    content hashes and the linkage are still checkable, which catches editing
    and reordering; only forgery by someone holding the key is out of reach,
    and that is out of reach for AGT too.
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

    checked = "hashes, chain and signatures" if secret_key is not None else "hashes and chain"
    return AgtVerifyResult(
        ok=True,
        message=f"{len(rows)} AGT entries verified ({checked})",
        entries=len(rows),
        signatures_checked=secret_key is not None,
    )


def agt_to_canonical(
    entry: dict[str, Any], *, host_id: str = "", fleet_id: str = ""
) -> dict[str, Any]:
    """Map one AGT entry onto an Agentmetry canonical event.

    MITRE tagging and traits are computed here rather than carried across,
    because AGT does not produce them and they are what lets the sequence rules
    see this activity at all. That is the point of the adapter: AGT decides
    allow or deny per call, and Agentmetry says what a session of those calls
    adds up to.
    """
    from agentmetry.core.audit.detection.traits import classify_command
    from agentmetry.core.audit.atlas import attach_atlas
    from agentmetry.core.audit.canonical import SCHEMA_VERSION
    from agentmetry.core.audit.mitre import get_mitre_mapping

    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    resource = str(entry.get("resource") or "")
    command = str(data.get("command") or "")
    event_type = str(entry.get("event_type") or "")
    verdict = str(entry.get("action") or "")
    outcome = str(entry.get("outcome") or "") or _OUTCOME.get(verdict, "success")

    reason_parts = [p for p in (entry.get("policy_decision"), entry.get("matched_rule")) if p]

    tool: dict[str, Any] = {
        "name": resource.rsplit(".", 1)[-1] if resource else "",
        "qualified": resource,
        "server": resource.split(".", 1)[0] if "." in resource else "agt",
        "arguments": data,
        "parameters_redacted": False,
    }
    if command:
        tool["command"] = command
        tool["input_hash"] = hashlib.sha256(command.encode()).hexdigest()
        tool["input_redaction"] = "hash+command"
        traits = classify_command(command)
        if traits:
            tool["traits"] = traits
    mapping = get_mitre_mapping(resource or "run", data or command)
    if mapping:
        tool["mitre"] = mapping
    attach_atlas(tool)

    agent_did = str(entry.get("agent_did") or "")

    return {
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
        "source_topic": f"external/agt/{_ACTION_TYPE.get(event_type, event_type or 'tool_called')}",
        "source": {"tier": "external", "app": "agt", "adapter": "agt_file"},
        "actor": {"type": "agent", "id": agent_did, "role": "agent"},
        "initiator": {"actor_type": "agent", "trigger": "agt", "operator_id": agent_did},
        "action": {
            "type": _ACTION_TYPE.get(event_type, "tool_called"),
            "outcome": outcome,
            "reason": "; ".join(str(p) for p in reason_parts),
        },
        "agent": {"name": agent_did or "agt", "skill_id": ""},
        "model": {"id": "", "provider": ""},
        "tool": tool,
        # Custody. Agentmetry did not observe this call; it read AGT's record of
        # it. A trail that cannot say so is asserting more than it knows.
        "provenance": {
            "captured_by": "agent-governance-toolkit",
            "agt_entry_id": entry.get("entry_id"),
            "agt_content_hash": entry.get("content_hash"),
            "agt_previous_hash": entry.get("previous_hash"),
            "agt_event_type": event_type,
            "agt_verdict": verdict,
            "verified_on_import": True,
        },
    }


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
    events = [agt_to_canonical(r, host_id=host_id, fleet_id=fleet_id) for r in rows]
    return result, events
