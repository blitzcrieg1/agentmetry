"""ASCII timeline rendering for `blackbox replay`."""

from __future__ import annotations

from typing import Any

from core.audit.canonical import normalize_outbox_row

_ICONS = {
    "session_start": "▶",
    "session_end": "■",
    "approval_request": "⏸",
    "approval_response": "✓",
    "tool_called": "🔧",
    "config_change": "⚙",
}


def format_timeline(rows: list[dict[str, Any]], *, thread_id: str) -> str:
    if not rows:
        return f"No audit events for thread_id={thread_id}"

    lines = [f"Agentmetry replay — correlation_id={thread_id}", f"{'─' * 60}"]

    for row in rows:
        canonical = normalize_outbox_row(row)
        if canonical is None:
            ts = row.get("ts", "?")
            topic = row.get("topic", "?")
            lines.append(f"  {ts}  [{topic}]")
            continue

        ts = canonical["timestamp_utc"][:19].replace("T", " ")
        action = canonical["action"]
        icon = _ICONS.get(action["type"], "·")
        outcome = action["outcome"]
        label = action["type"]

        detail_parts: list[str] = []
        if skill := canonical.get("agent", {}).get("skill_id"):
            detail_parts.append(f"skill={skill}")
        if tool := canonical.get("tool"):
            detail_parts.append(f"tool={tool.get('qualified') or tool.get('name')}")
            if outcome == "denied" and action.get("reason"):
                detail_parts.append(f"reason={action['reason']}")
        if action.get("reason") and action["type"] == "approval_response":
            detail_parts.append(action["reason"])

        detail = f"  ({', '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"  {ts}  {icon} {label}/{outcome}{detail}  seq={canonical.get('seq')}")

    lines.append(f"{'─' * 60}")
    lines.append(f"{len(rows)} event(s)")
    return "\n".join(lines)
