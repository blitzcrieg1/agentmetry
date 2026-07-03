"""Node telemetry — streams live graph updates and persists a per-thread trace."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.bus.bus import bus
from core.bus.events import RUN_NODE


def node_events_path() -> Path:
    root = Path(__file__).resolve().parents[2] / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root / "node-events.jsonl"


def _log_node_event(
    thread_id: str,
    session_id: str,
    node: str,
    status: str,
    snippet: str,
    metrics: dict[str, Any] | None,
) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "session_id": session_id,
        "node": node,
        "status": status,
        "output": snippet,
        "metrics": metrics or {},
    }
    with node_events_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")


async def emit_node(
    session_id: str,
    thread_id: str,
    node: str,
    status: str,
    *,
    output: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    snippet = output[:500] + ("..." if len(output) > 500 else "")

    if thread_id:
        _log_node_event(thread_id, session_id, node, status, snippet, metrics)

    if not session_id:
        return
    bus.publish(
        RUN_NODE,
        {
            "type": "node_update",
            "node": node,
            "status": status,
            "output": snippet,
            "metrics": metrics or {},
        },
        session_id=session_id,
        thread_id=thread_id,
    )
