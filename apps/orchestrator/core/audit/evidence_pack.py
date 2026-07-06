"""Assemble tamper-evident compliance evidence packs from the audit trail.

Reads the durable event outbox (events.db) and run ledger (runs.jsonl) — no
kernel changes, no live orchestrator required. v1 exports JSON with an
integrity hash; PDF/Merkle verification can extend this module later.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from core.bus.events import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_TERMINATED,
    RUN_WAITING,
    TOOL_CALLED,
    TOOL_DENIED,
)
from core.bus.outbox import EventOutbox, get_outbox
from core.config import settings
from core.notifiers.audit import read_runs_between

SCHEMA_VERSION = "1.0"

_COMPLIANCE_MAPPING = {
    "art_12_logging": (
        "EU AI Act Art. 12 (logging): events[] and runs[] record timestamps, "
        "inputs/outputs, tool invocations, and lifecycle transitions with "
        "monotonic seq ordering in the outbox."
    ),
    "art_13_transparency": (
        "EU AI Act Art. 13 (transparency): tool_calls[] records tool name, "
        "arguments, and outcomes; runs[] records skill name, session, and status."
    ),
    "art_14_human_oversight": (
        "EU AI Act Art. 14 (human oversight): approvals[] records every "
        "human_approval gate (waiting, approved, terminated) with draft text "
        "and confidence where captured."
    ),
    "disclaimer": (
        "This pack is an operator-generated audit artifact. It is not legal "
        "advice or a certification of EU AI Act compliance. Map requirements "
        "to your deployer's risk classification with qualified counsel."
    ),
}


def date_range_to_timestamps(from_date: date, to_date: date) -> tuple[str, str]:
    """Inclusive calendar dates → UTC ISO bounds for outbox/ledger queries."""
    if to_date < from_date:
        raise ValueError("--to must be on or after --from")
    start = datetime.combine(from_date, time.min, tzinfo=timezone.utc).isoformat()
    end = datetime.combine(to_date, time.max, tzinfo=timezone.utc).isoformat()
    return start, end


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _extract_runs(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize run ledger rows for the evidence bundle."""
    runs: list[dict[str, Any]] = []
    for row in run_rows:
        runs.append({
            "ts": row.get("ts"),
            "thread_id": row.get("thread_id"),
            "skill": row.get("skill"),
            "status": row.get("status"),
            "session_id": row.get("session_id"),
            "triggered_by": row.get("triggered_by"),
            "trigger_rule_id": row.get("trigger_rule_id"),
            "cost": row.get("cost"),
            "latency_ms": row.get("latency_ms"),
            "archive_path": row.get("archive_path"),
            "error": row.get("error"),
        })
    return runs


def _extract_tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for ev in events:
        if ev["topic"] not in (TOOL_CALLED, TOOL_DENIED):
            continue
        payload = ev.get("payload") or {}
        tools.append({
            "seq": ev["seq"],
            "ts": ev["ts"],
            "thread_id": ev.get("thread_id") or payload.get("thread_id"),
            "session_id": ev.get("session_id"),
            "topic": ev["topic"],
            "tool": payload.get("tool"),
            "skill": payload.get("skill"),
            "sandboxed": payload.get("sandboxed"),
            "argv": payload.get("argv"),
            "exit_code": payload.get("exit_code"),
            "denied": ev["topic"] == TOOL_DENIED,
        })
    return tools


def _extract_approvals(
    events: list[dict[str, Any]], run_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Reconstruct approval gate decisions from bus events + run ledger."""
    gates: dict[str, dict[str, Any]] = {}

    for ev in events:
        tid = ev.get("thread_id") or (ev.get("payload") or {}).get("thread_id")
        if not tid:
            continue
        payload = ev.get("payload") or {}

        if ev["topic"] == RUN_WAITING:
            gates.setdefault(tid, {"thread_id": tid})
            gates[tid].update({
                "gate": "human_approval",
                "waiting_at": ev["ts"],
                "draft": payload.get("draft"),
                "confidence": payload.get("confidence"),
                "session_id": ev.get("session_id"),
            })
        elif ev["topic"] == RUN_COMPLETED and payload.get("type") == "execution_completed":
            if tid in gates:
                gates[tid]["decision"] = "approved"
                gates[tid]["decided_at"] = ev["ts"]
                metrics = payload.get("metrics") or {}
                gates[tid]["final_cost"] = metrics.get("cost")
                gates[tid]["archive_path"] = payload.get("archive_path")
        elif ev["topic"] == RUN_TERMINATED:
            if tid in gates:
                gates[tid]["decision"] = "terminated"
                gates[tid]["decided_at"] = ev["ts"]
        elif ev["topic"] == RUN_FAILED and tid in gates:
            gates[tid]["decision"] = "failed"
            gates[tid]["decided_at"] = ev["ts"]
            gates[tid]["error"] = payload.get("error")

    # Ledger rows refine decision labels (approved vs waiting_for_input).
    for row in run_rows:
        tid = row.get("thread_id")
        if not tid or tid not in gates:
            continue
        status = row.get("status")
        if status == "approved":
            gates[tid]["decision"] = "approved"
            gates[tid]["decided_at"] = row.get("ts")
        elif status == "terminated":
            gates[tid]["decision"] = "terminated"
            gates[tid]["decided_at"] = row.get("ts")
        elif status == "waiting_for_input" and "decision" not in gates[tid]:
            gates[tid]["decision"] = "pending"

    return sorted(gates.values(), key=lambda g: g.get("waiting_at") or "")


def _summarize(runs: list, approvals: list, tool_calls: list, events: list) -> dict[str, int]:
    decisions = [a.get("decision") for a in approvals]
    return {
        "event_count": len(events),
        "run_ledger_rows": len(runs),
        "approval_gates": len(approvals),
        "approvals_granted": sum(1 for d in decisions if d == "approved"),
        "approvals_terminated": sum(1 for d in decisions if d == "terminated"),
        "approvals_pending": sum(1 for d in decisions if d == "pending"),
        "tool_calls": sum(1 for t in tool_calls if not t.get("denied")),
        "tool_denials": sum(1 for t in tool_calls if t.get("denied")),
        "runs_started": sum(1 for e in events if e["topic"] == RUN_STARTED),
        "runs_failed": sum(1 for e in events if e["topic"] == RUN_FAILED),
    }


def _integrity_hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_evidence_pack(
    from_date: date,
    to_date: date,
    *,
    outbox: EventOutbox | None = None,
    vault_path: Path | None = None,
) -> dict[str, Any]:
    """Build a complete evidence pack dict (includes integrity hash in meta)."""
    start_ts, end_ts = date_range_to_timestamps(from_date, to_date)
    box = outbox or get_outbox()
    events = box.read_between(start_ts, end_ts)
    run_rows = read_runs_between(start_ts, end_ts)

    runs = _extract_runs(run_rows)
    tool_calls = _extract_tool_calls(events)
    approvals = _extract_approvals(events, run_rows)

    body = {
        "runs": runs,
        "approvals": approvals,
        "tool_calls": tool_calls,
        "events": events,
        "compliance_mapping": dict(_COMPLIANCE_MAPPING),
        "summary": _summarize(runs, approvals, tool_calls, events),
    }

    vault = vault_path or settings.vault_path
    pack = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "date_from": from_date.isoformat(),
            "date_to": to_date.isoformat(),
            "vault_path": str(vault),
            "query_start_ts": start_ts,
            "query_end_ts": end_ts,
        },
        **body,
    }
    pack["meta"]["integrity_sha256"] = _integrity_hash(body)
    return pack


def write_evidence_pack(
    pack: dict[str, Any],
    output: Path,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(pack, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return output


def default_export_path(from_date: date, to_date: date, vault_path: Path | None = None) -> Path:
    vault = vault_path or settings.vault_path
    name = f"evidence-{from_date.isoformat()}_to_{to_date.isoformat()}.json"
    return vault / "30-Archive" / "exports" / name


def verify_evidence_pack(pack: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, message). Recomputes integrity_sha256 over the body."""
    meta = pack.get("meta") or {}
    stored = meta.get("integrity_sha256")
    if not stored:
        return False, "missing meta.integrity_sha256"

    body = {
        "runs": pack.get("runs", []),
        "approvals": pack.get("approvals", []),
        "tool_calls": pack.get("tool_calls", []),
        "events": pack.get("events", []),
        "compliance_mapping": pack.get("compliance_mapping", {}),
        "summary": pack.get("summary", {}),
    }
    expected = _integrity_hash(body)
    if expected != stored:
        return False, f"integrity mismatch (expected {expected[:16]}…, got {stored[:16]}…)"
    return True, "integrity verified"
