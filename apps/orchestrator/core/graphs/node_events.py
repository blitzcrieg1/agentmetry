"""WebSocket node telemetry — emits live graph updates to the dashboard."""

from __future__ import annotations

from typing import Any

from api.websocket import ws_manager


async def emit_node(
    session_id: str,
    node: str,
    status: str,
    *,
    output: str = "",
    metrics: dict[str, Any] | None = None,
) -> None:
    if not session_id:
        return
    snippet = output[:500] + ("..." if len(output) > 500 else "")
    await ws_manager.send_node_update(
        session_id,
        node,
        status,
        output=snippet,
        metrics=metrics or {},
    )
