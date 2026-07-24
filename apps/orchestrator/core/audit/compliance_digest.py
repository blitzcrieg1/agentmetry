"""Periodic governance digest — the artifact a reviewer files, not investigates.

The evidence pack and this digest serve different readers, which is why they are
separate documents. A pack is for an incident investigator: every event, every
hash, verifiable against the chain. A digest is for the monthly control review
required by EN 18286 cl. 7, ISO/IEC 42001 cl. 9 and AI Act Art. 72 — what
happened, what fired, what was in force, and what still needs a human.

It is a projection of the evidence pack, so the two can never disagree about the
period they describe.

Renders as Markdown for filing, or JSON when something downstream wants to parse
it. Neither form contains command text or arguments.
"""

from __future__ import annotations

from datetime import date
from typing import Any

_SEVERITY_ORDER = ("critical", "high", "medium", "low")


def build_digest(
    from_date: date,
    to_date: date,
    *,
    trail_db: Any | None = None,
) -> dict[str, Any]:
    """Build the digest from the same source the evidence pack uses."""
    from core.audit.evidence_pack import build_evidence_pack

    pack = build_evidence_pack(
        from_date, to_date, trail_db=trail_db, include_raw_events=False
    )
    summary = pack["summary"]
    detections = pack["detections"]

    by_rule: dict[str, dict[str, Any]] = {}
    for detection in detections:
        rule_id = str(detection.get("rule_id") or "unknown")
        entry = by_rule.setdefault(
            rule_id,
            {
                "rule_id": rule_id,
                "title": detection.get("title") or rule_id,
                "severity": detection.get("severity") or "unknown",
                "count": 0,
                "sessions": set(),
                "first_seen_utc": detection.get("first_seen_utc"),
                "last_seen_utc": detection.get("last_seen_utc"),
            },
        )
        entry["count"] += 1
        if detection.get("correlation_id"):
            entry["sessions"].add(str(detection["correlation_id"]))
        last = detection.get("last_seen_utc")
        if last and (not entry["last_seen_utc"] or last > entry["last_seen_utc"]):
            entry["last_seen_utc"] = last

    findings = sorted(
        (
            {**entry, "sessions": len(entry["sessions"])}
            for entry in by_rule.values()
        ),
        key=lambda f: (
            _SEVERITY_ORDER.index(f["severity"])
            if f["severity"] in _SEVERITY_ORDER
            else len(_SEVERITY_ORDER),
            -f["count"],
        ),
    )

    return {
        "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "generated_at": pack["meta"]["exported_at"],
        "activity": {
            "events": summary["event_count"],
            "sessions": summary["sessions"],
            "agents": summary["agents"],
            "tool_calls": summary["tool_calls"],
            "tool_denials": summary["tool_denials"],
        },
        "oversight": {
            "approval_gates": summary["approval_gates"],
            "granted": summary["approvals_granted"],
            "denied": summary["approvals_denied"],
            "pending": summary["approvals_pending"],
            "inferred": summary["approvals_inferred"],
        },
        "findings": findings,
        "findings_by_severity": summary["detections_by_severity"],
        "dlp_hits": summary["dlp_hits"],
        "tool_policy_hits": summary["tool_policy_hits"],
        "controls": pack["controls"],
        "trail_chain": pack["meta"]["trail_chain"],
        "evidence_integrity_sha256": pack["meta"]["integrity_sha256"],
    }


def _pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.0f}%" if whole else "n/a"


def render_markdown(digest: dict[str, Any]) -> str:
    """Render the digest for filing. Deliberately blunt about weak evidence."""
    period = digest["period"]
    act = digest["activity"]
    ovr = digest["oversight"]
    chain = digest["trail_chain"]
    controls = digest["controls"]

    lines: list[str] = [
        f"# Agentmetry compliance digest — {period['from']} to {period['to']}",
        "",
        f"Generated {digest['generated_at']}",
        "",
        "## Activity",
        "",
        f"- **{act['events']}** events across **{act['sessions']}** sessions",
        f"- **{act['tool_calls']}** tool calls, **{act['tool_denials']}** denied",
    ]
    if act["agents"]:
        agents = ", ".join(f"{name} ({n})" for name, n in sorted(act["agents"].items()))
        lines.append(f"- Agents: {agents}")

    lines += [
        "",
        "## Human oversight (AI Act Art. 14)",
        "",
        f"- **{ovr['approval_gates']}** approval gates: "
        f"{ovr['granted']} granted, {ovr['denied']} denied, {ovr['pending']} pending",
    ]
    if ovr["approval_gates"]:
        share = _pct(ovr["inferred"], ovr["approval_gates"])
        lines.append(
            f"- **{ovr['inferred']} ({share}) were inferred, not observed.** No IDE "
            "reports the human's click; these were derived from the event stream "
            "and must not be cited as evidence of a human decision."
        )

    lines += ["", "## Findings", ""]
    if not digest["findings"]:
        lines.append("No detections fired in this period.")
    else:
        lines += [
            "| Severity | Rule | Count | Sessions | Last seen |",
            "|----------|------|-------|----------|-----------|",
        ]
        for finding in digest["findings"]:
            lines.append(
                f"| {finding['severity']} | {finding['rule_id']} | {finding['count']} "
                f"| {finding['sessions']} | {finding.get('last_seen_utc') or '—'} |"
            )
        lines += [
            "",
            "*Each finding needs a triage note: confirmed, false positive, or "
            "accepted risk. An untriaged detection is not evidence of control.*",
        ]

    if digest["dlp_hits"]:
        lines += ["", "## DLP matches", ""]
        for rule_id, count in sorted(digest["dlp_hits"].items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{rule_id}`: {count}")

    if digest["tool_policy_hits"]:
        lines += ["", "## Tool policy matches", ""]
        for rule_id, count in sorted(
            digest["tool_policy_hits"].items(), key=lambda kv: -kv[1]
        ):
            lines.append(f"- `{rule_id}`: {count}")

    dlp_manifest = controls["dlp"]["manifest"].get("sha256") or "absent"
    tp_manifest = controls["tool_policy"]["manifest"].get("sha256") or "absent"
    lines += [
        "",
        "## Controls in force",
        "",
        f"- DLP mode **{controls['dlp']['mode']}** — manifest `{dlp_manifest[:16]}`",
        f"- Tool policy mode **{controls['tool_policy']['mode']}** — manifest `{tp_manifest[:16]}`",
        f"- Operator: `{controls['operator_id']}`",
    ]
    if controls["dlp"]["mode"] != "block" or controls["tool_policy"]["mode"] != "block":
        lines.append(
            "- *Note: `log` mode records matches but does not prevent them. "
            "This period evidences detection, not prevention.*"
        )

    lines += [
        "",
        "## Trail integrity (AI Act Art. 12)",
        "",
        f"- Chain verified: **{chain.get('verified')}** — {chain.get('message', '')}",
        f"- Head: seq {chain.get('head_seq')} `{str(chain.get('head_sha256') or '')[:32]}`",
        f"- Evidence pack integrity: `{digest['evidence_integrity_sha256'][:32]}`",
        "",
        "Record the chain head somewhere the audited machine cannot write. A local "
        "hash chain proves in-place edits and reordering; it cannot prove the file "
        "was not truncated.",
        "",
        "---",
        "",
        "*Operator-generated artifact. Not legal advice, not a certification. "
        "Agentmetry records the agents wired into it; absence of an event is not "
        "evidence that nothing happened outside the monitored boundary.*",
    ]
    return "\n".join(lines) + "\n"
