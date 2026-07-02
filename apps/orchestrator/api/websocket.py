"""WebSocket connection manager for real-time telemetry streaming."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        if session_id not in self.active:
            self.active[session_id] = []
        self.active[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        if session_id in self.active:
            self.active[session_id] = [
                ws for ws in self.active[session_id] if ws != websocket
            ]
            if not self.active[session_id]:
                del self.active[session_id]

    async def broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        if session_id not in self.active:
            return
        payload = json.dumps(event)
        dead: list[WebSocket] = []
        for ws in self.active[session_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, session_id)

    async def send_node_update(
        self,
        session_id: str,
        node: str,
        status: str,
        *,
        output: str = "",
        metrics: dict[str, Any] | None = None,
    ) -> None:
        await self.broadcast(session_id, {
            "type": "node_update",
            "node": node,
            "status": status,
            "output": output,
            "metrics": metrics or {},
        })

    async def send_approval_request(
        self,
        session_id: str,
        thread_id: str,
        draft: str,
        confidence: float,
    ) -> None:
        await self.broadcast(session_id, {
            "type": "approval_required",
            "thread_id": thread_id,
            "draft": draft,
            "confidence": confidence,
            "status": "waiting_for_input",
        })

    async def send_token_stream(self, session_id: str, token: str, node: str) -> None:
        await self.broadcast(session_id, {
            "type": "token",
            "token": token,
            "node": node,
        })


ws_manager = ConnectionManager()
