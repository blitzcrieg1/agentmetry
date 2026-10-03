"""ASCII timeline rendering for `agentmetry replay`.

Replay read only the legacy outbox (`events.db`), which nothing has written to
since the agent runtime was removed: every hook, MCP and OTel event lives in
the chained trail, so `agentmetry replay <session>` printed "No audit events"
for every real session. It reads the trail now, every segment of it, and
falls back to the outbox only for runs that predate the trail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentmetry.core.audit.canonical import normalize_outbox_row


def _is_canonical(row: dict[str, Any]) -> bool:
    return isinstance(row.get("action"), dict) and "timestamp_utc" in row


def read_trail_events(trail_path: Path, correlation_id: str) -> list[dict[str, Any]]:
    """Canonical events whose correlation or session id matches, oldest first."""
    from agentmetry.core.audit.forwarder import trail_segments
    from agentmetry.core.audit.trail_chain import unwrap_trail_record

    wanted = correlation_id.strip()
    out: list[dict[str, Any]] = []
    for path in trail_segments(trail_path):
        try:
            fh = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if wanted not in line:
                    continue  # cheap pre-filter; the id is a substring of the line
                try:
                    event = unwrap_trail_record(json.loads(line))
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if wanted in (str(event.get("correlation_id") or ""), str(event.get("session_id") or "")):
                    out.append(event)
    return out

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
        canonical = row if _is_canonical(row) else normalize_outbox_row(row)
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
        seq = canonical.get("seq")
        lines.append(f"  {ts}  {icon} {label}/{outcome}{detail}" + (f"  seq={seq}" if seq is not None else ""))

    lines.append(f"{'─' * 60}")
    lines.append(f"{len(rows)} event(s)")
    return "\n".join(lines)
