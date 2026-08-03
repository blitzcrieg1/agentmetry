"""Assemble tamper-evident compliance evidence packs from the audit trail.

Reads the canonical Tier B trail (`audit.db`) — the same events the dashboard
and the SIEM sinks see — and binds each pack to a verifiable position in the
JSONL hash chain.

History worth keeping: until 2026-07-24 this module read the legacy event
outbox and `runs.jsonl` from the removed governed runtime. The hook ingest path
never published to that bus, so on a recorder-only install the flagship
compliance export contained driver-mount noise while thousands of captured
agent tool calls sat in the trail, unexported. Anything added here must read the
trail; if a future feature needs a second source, it belongs alongside the
trail, never instead of it.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

from agentmetry.core.audit.detection.disposition import extract_dispositions
from agentmetry.core.config import settings
from agentmetry.core.version import __version__

SCHEMA_VERSION = "2.1"


_COMPLIANCE_MAPPING = {
    "art_12_logging": (
        "EU AI Act Art. 12 (record-keeping): events[] is the canonical, "
        "time-ordered record of every captured agent tool call, approval gate "
        "and correlated detection, with per-event input hashes. "
        "meta.trail_chain binds this pack to a position in the tamper-evident "
        "JSONL hash chain, verifiable with `agentmetry verify --trail`."
    ),
    "art_14_human_oversight": (
        "EU AI Act Art. 14 (human oversight): approvals[] records each gated "
        "action and its resolution. Entries carry `inferred: true` when the "
        "response was derived from the event stream rather than observed from "
        "the IDE — no IDE reports the human's click, and an auditor must be "
        "able to tell the difference."
    ),
    "art_15_cybersecurity": (
        "EU AI Act Art. 15 (accuracy, robustness, cybersecurity): detections[] "
        "records correlated behavioural findings (credential exfiltration, "
        "guardrail bypass, download cradles, agent data injection). "
        "controls[] records the DLP and tool-policy manifests in force, with "
        "content hashes and enforcement modes."
    ),
    "art_17_qms": (
        "EU AI Act Art. 17 / EN 18286 cl. 6 (operation and control): the pack "
        "evidences which agents acted, under which policy configuration, and "
        "what was denied — process evidence for a quality management system "
        "covering AI-assisted development."
    ),
    "iso_42001_cl10_corrective_action": (
        "ISO/IEC 42001 cl. 10 / EN 18286 cl. 8 (corrective action): "
        "dispositions[] records what a human decided about each finding — "
        "acknowledged, resolved, false positive or accepted risk — with the "
        "decider, the timestamp and the written justification. Each decision "
        "is itself an event on the same hash chain as the detection it "
        "answers, and superseded decisions are retained. "
        "summary.detections_untriaged is the count of findings with no human "
        "decision at all; that number is the honest measure of whether the "
        "detection capability is operating as a control."
    ),
    "art_72_post_market": (
        "EU AI Act Art. 72 (post-market monitoring): summary[] and detections[] "
        "support periodic review; the trail supports incident reconstruction "
        "within Art. 73 reporting windows."
    ),
    "scope_limits": (
        "Agentmetry records the agents wired into it via IDE hooks and the MCP "
        "audit proxy. It does not observe unmanaged assistants (browser "
        "ChatGPT, unhooked IDEs) and is not a CASB, a sandbox, or a model "
        "evaluation tool. Absence of an event is not evidence that nothing "
        "happened outside the monitored boundary."
    ),
    "disclaimer": (
        "This pack is an operator-generated audit artifact. It is not legal "
        "advice or a certification of EU AI Act compliance. Map requirements "
        "to your risk classification with qualified counsel."
    ),
}


def date_range_to_timestamps(from_date: date, to_date: date) -> tuple[str, str]:
    """Inclusive calendar dates → UTC ISO bounds for trail queries."""
    if to_date < from_date:
        raise ValueError("--to must be on or after --from")
    start = datetime.combine(from_date, time.min, tzinfo=timezone.utc).isoformat()
    end = datetime.combine(to_date, time.max, tzinfo=timezone.utc).isoformat()
    return start, end


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


# --- canonical event accessors ------------------------------------------------
# Events are plain dicts read back from SQLite; never assume a nested key exists.


def _action(event: dict[str, Any]) -> dict[str, Any]:
    action = event.get("action")
    return action if isinstance(action, dict) else {}


def _tool(event: dict[str, Any]) -> dict[str, Any]:
    tool = event.get("tool")
    return tool if isinstance(tool, dict) else {}


def _source_app(event: dict[str, Any]) -> str:
    source = event.get("source")
    return str(source.get("app") or "") if isinstance(source, dict) else ""


def _actor_type(event: dict[str, Any]) -> str:
    initiator = event.get("initiator")
    return str(initiator.get("actor_type") or "") if isinstance(initiator, dict) else ""


def _extract_tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in events:
        action = _action(event)
        if action.get("type") != "tool_called":
            continue
        tool = _tool(event)
        mitre = tool.get("mitre") if isinstance(tool.get("mitre"), dict) else {}
        entry: dict[str, Any] = {
            "ts": event.get("timestamp_utc"),
            "event_id": event.get("event_id"),
            "correlation_id": event.get("correlation_id"),
            "source_app": _source_app(event),
            "actor_type": _actor_type(event),
            "tool": tool.get("qualified"),
            "server": tool.get("server"),
            "input_hash": tool.get("input_hash"),
            "outcome": action.get("outcome"),
            "reason": action.get("reason"),
            "denied": action.get("outcome") == "denied",
            "tactic_id": mitre.get("tactic_id"),
            "technique_id": mitre.get("technique_id"),
        }
        # Command text is opt-in (AGENTMETRY_AUDIT_LOG_COMMANDS); traits are the
        # privacy-preserving classification that is always available.
        if tool.get("command"):
            entry["command"] = tool.get("command")
        if tool.get("traits"):
            entry["traits"] = tool.get("traits")
        dlp = event.get("dlp")
        if isinstance(dlp, dict) and dlp.get("rule_id"):
            entry["dlp_rule_id"] = dlp.get("rule_id")
            entry["dlp_mode"] = dlp.get("mode")
        policy = event.get("tool_policy")
        if isinstance(policy, dict) and policy.get("rule_id"):
            entry["tool_policy_rule_id"] = policy.get("rule_id")
            entry["tool_policy_blocked"] = policy.get("blocked")
        calls.append(entry)
    return calls


def _extract_approvals(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair approval requests with their resolutions.

    `inferred` is load-bearing for an auditor: no IDE reports the human's click,
    so a response derived from the event stream must never be presented as an
    observed one.
    """
    gates: list[dict[str, Any]] = []
    open_by_corr: dict[str, list[int]] = {}

    for event in events:
        action = _action(event)
        atype = action.get("type")
        corr = str(event.get("correlation_id") or "")

        if atype == "approval_request":
            tool = _tool(event)
            gates.append({
                "correlation_id": corr,
                "source_app": _source_app(event),
                "requested_at": event.get("timestamp_utc"),
                "tool": tool.get("qualified"),
                "input_hash": tool.get("input_hash"),
                "decision": "pending",
                "inferred": False,
            })
            open_by_corr.setdefault(corr, []).append(len(gates) - 1)

        elif atype == "approval_response":
            reason = str(action.get("reason") or "")
            inferred = reason.startswith("inferred:")
            gated = event.get("gated_action")
            gated = gated if isinstance(gated, dict) else {}
            outcome = action.get("outcome")
            decision = "granted" if outcome == "success" else "denied"

            idx = None
            for candidate in open_by_corr.get(corr, []):
                gate = gates[candidate]
                if gate["decision"] != "pending":
                    continue
                want = str(gated.get("input_hash") or "")
                have = str(gate.get("input_hash") or "")
                if want and have and want != have:
                    continue
                idx = candidate
                break

            if idx is None:
                # A response with no recorded request still belongs in the pack.
                gates.append({
                    "correlation_id": corr,
                    "source_app": _source_app(event),
                    "requested_at": None,
                    "tool": gated.get("tool"),
                    "input_hash": gated.get("input_hash"),
                    "decision": decision,
                    "decided_at": event.get("timestamp_utc"),
                    "reason": reason,
                    "inferred": inferred,
                    "orphan_response": True,
                })
            else:
                gates[idx].update({
                    "decision": decision,
                    "decided_at": event.get("timestamp_utc"),
                    "reason": reason,
                    "inferred": inferred,
                })
    return gates


def _extract_detections(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for event in events:
        if _action(event).get("type") != "detection":
            continue
        detection = event.get("detection")
        if not isinstance(detection, dict):
            continue
        found.append({
            "ts": event.get("timestamp_utc"),
            "correlation_id": event.get("correlation_id"),
            "rule_id": detection.get("rule_id"),
            "title": detection.get("title"),
            "severity": detection.get("severity"),
            "summary": detection.get("summary"),
            "tactic_ids": detection.get("tactic_ids"),
            "technique_ids": detection.get("technique_ids"),
            "event_ids": detection.get("event_ids"),
            "first_seen_utc": detection.get("first_seen_utc"),
            "last_seen_utc": detection.get("last_seen_utc"),
        })
    return found


def _file_sha256(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "sha256": None, "present": False}
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "present": True,
    }


def _controls_snapshot() -> dict[str, Any]:
    """The enforcement configuration in force — the control-state evidence.

    Replaces the old drivers.json snapshot, which described demo MCP drivers
    that a recorder-only install does not have.
    """
    return {
        "dlp": {
            "mode": settings.dlp_mode,
            "manifest": _file_sha256(Path(settings.dlp_rules_path)),
        },
        "tool_policy": {
            "mode": settings.tool_policy_mode,
            "manifest": _file_sha256(Path(settings.tool_policy_path)),
        },
        "detection": {
            "off_hours_enabled": settings.detect_off_hours,
        },
        "operator_id": settings.operator_id.strip() or "local",
    }


def _trail_chain_state() -> dict[str, Any]:
    """Bind the pack to a verifiable chain position.

    Without this a pack is an unanchored JSON blob; with it, a reviewer can run
    `agentmetry verify --trail` and confirm the trail still matches the state
    this pack was drawn from.
    """
    trail_path = Path(settings.audit_export_path)
    try:
        from agentmetry.core.audit.trail_chain import verify_trail_file

        result = verify_trail_file(trail_path)
        return {
            "path": str(trail_path),
            "verified": result.ok,
            "message": result.message,
            "head_seq": result.head_seq,
            "head_sha256": result.head_sha256,
            "lines_chained": result.lines_chained,
            "lines_legacy": result.lines_legacy,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"path": str(trail_path), "verified": False, "message": str(exc)}


def _attach_dispositions(detections: list[dict[str, Any]]) -> dict[str, int]:
    """Stamp each detection with the triage state in force, and count them.

    Read from the disposition index rather than the events in this period on
    purpose: a detection that fired in June and was closed in July is closed,
    and a pack that showed it as untriaged would misrepresent the control.
    """
    from agentmetry.core.audit.detection.disposition import DEFAULT_STATUS, get_disposition_store

    store = get_disposition_store()
    counts: Counter[str] = Counter()
    for detection in detections:
        current = store.get(
            str(detection.get("correlation_id") or ""),
            str(detection.get("rule_id") or ""),
        )
        detection["disposition"] = current
        counts[current["status"] if current else DEFAULT_STATUS] += 1
    return dict(counts)


def _summarize(
    events: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
    detections: list[dict[str, Any]],
    disposition_counts: dict[str, int],
) -> dict[str, Any]:
    from agentmetry.core.audit.detection.disposition import CLOSED_STATUSES

    decisions = Counter(a.get("decision") for a in approvals)
    triaged = sum(n for status, n in disposition_counts.items() if status != "new")
    return {
        "event_count": len(events),
        "tool_calls": sum(1 for t in tool_calls if not t["denied"]),
        "tool_denials": sum(1 for t in tool_calls if t["denied"]),
        "sessions": len({e.get("correlation_id") for e in events if e.get("correlation_id")}),
        "agents": dict(Counter(_source_app(e) for e in events if _source_app(e))),
        "approval_gates": len(approvals),
        "approvals_granted": decisions.get("granted", 0),
        "approvals_denied": decisions.get("denied", 0),
        "approvals_pending": decisions.get("pending", 0),
        "approvals_inferred": sum(1 for a in approvals if a.get("inferred")),
        "detections": len(detections),
        "detections_by_severity": dict(Counter(d.get("severity") for d in detections)),
        "detections_by_rule": dict(Counter(d.get("rule_id") for d in detections)),
        "detections_by_disposition": disposition_counts,
        "detections_triaged": triaged,
        "detections_untriaged": disposition_counts.get("new", 0),
        "detections_closed": sum(
            n for status, n in disposition_counts.items() if status in CLOSED_STATUSES
        ),
        "dlp_hits": dict(
            Counter(t["dlp_rule_id"] for t in tool_calls if t.get("dlp_rule_id"))
        ),
        "tool_policy_hits": dict(
            Counter(t["tool_policy_rule_id"] for t in tool_calls if t.get("tool_policy_rule_id"))
        ),
    }


def _integrity_hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_BODY_KEYS = (
    "events",
    "tool_calls",
    "approvals",
    "detections",
    "dispositions",
    "controls",
    "compliance_mapping",
    "summary",
)


def build_evidence_pack(
    from_date: date,
    to_date: date,
    *,
    trail_db: Any | None = None,
    include_raw_events: bool = True,
) -> dict[str, Any]:
    """Build a complete evidence pack dict (includes integrity hash in meta)."""
    start_ts, end_ts = date_range_to_timestamps(from_date, to_date)

    if trail_db is None:
        from agentmetry.core.audit.trail_db import get_trail_db

        trail_db = get_trail_db()
    events = trail_db.read_between(start_ts, end_ts)

    tool_calls = _extract_tool_calls(events)
    approvals = _extract_approvals(events)
    detections = _extract_detections(events)
    disposition_counts = _attach_dispositions(detections)

    body = {
        "events": events if include_raw_events else [],
        "tool_calls": tool_calls,
        "approvals": approvals,
        "detections": detections,
        # The decisions made in this period, in the order they were made. The
        # `detections` entries above carry the state currently in force; this
        # is the audit trail of how it got there.
        "dispositions": extract_dispositions(events),
        "controls": _controls_snapshot(),
        "compliance_mapping": dict(_COMPLIANCE_MAPPING),
        "summary": _summarize(
            events, tool_calls, approvals, detections, disposition_counts
        ),
    }

    pack = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            # An auditor reading this pack in 2028 needs to know which build
            # produced it: rules, redaction, and mappings all move between
            # versions. Provenance, not decoration.
            "producer": f"agentmetry/{__version__}",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "date_from": from_date.isoformat(),
            "date_to": to_date.isoformat(),
            "query_start_ts": start_ts,
            "query_end_ts": end_ts,
            "source": "audit_trail",
            "raw_events_included": include_raw_events,
            "trail_chain": _trail_chain_state(),
        },
        **body,
    }
    pack["meta"]["integrity_sha256"] = _integrity_hash(body)
    return pack


def write_evidence_pack(pack: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(pack, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return output


def default_export_path(
    from_date: date, to_date: date, vault_path: Path | None = None
) -> Path:
    """Where an export lands by default.

    Keeps the documented vault archive location when a vault exists, and falls
    back to `data/exports/` next to the trail when it does not — a recorder-only
    install has no vault, and compliance exports must still have a home.
    """
    name = f"evidence-{from_date.isoformat()}_to_{to_date.isoformat()}.json"
    vault = Path(vault_path) if vault_path else Path(settings.vault_path)
    if vault.is_dir():
        return vault / "30-Archive" / "exports" / name
    return Path(settings.audit_export_path).parent / "exports" / name


def verify_evidence_pack(pack: dict[str, Any]) -> tuple[bool, str]:
    """Return (ok, message). Recomputes integrity_sha256 over the body."""
    meta = pack.get("meta") or {}
    stored = meta.get("integrity_sha256")
    if not stored:
        return False, "missing meta.integrity_sha256"

    body = {key: pack.get(key, [] if key != "controls" else {}) for key in _BODY_KEYS}
    # compliance_mapping and summary default to dicts, not lists.
    for key in ("compliance_mapping", "summary"):
        if not isinstance(body.get(key), dict):
            body[key] = {}

    expected = _integrity_hash(body)
    if expected != stored:
        return False, f"integrity mismatch (expected {expected[:16]}…, got {stored[:16]}…)"
    return True, "integrity verified"
