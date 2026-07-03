"""WebSocket connection manager for real-time telemetry streaming."""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket


# Session id that mirrors every event; the dashboard subscribes to it to
# observe autonomous runs that happen in other sessions.
GLOBAL_SESSION = "global"


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
        await self._send(session_id, event)
        if session_id != GLOBAL_SESSION:
            await self._send(GLOBAL_SESSION, {**event, "origin_session": session_id})

    async def _send(self, session_id: str, event: dict[str, Any]) -> None:
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


ws_manager = ConnectionManager()
