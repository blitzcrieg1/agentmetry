"""WebSocket bridge — the only place bus events meet the transport layer.

Forwards each session-addressed event's payload verbatim (plus its outbox seq
for replay), preserving the existing wire format and the global-session mirror
implemented by ConnectionManager.broadcast.
"""

from __future__ import annotations

import logging

from api.websocket import ConnectionManager, ws_manager
from core.bus.bus import EventBus, bus

logger = logging.getLogger(__name__)


async def ws_event_bridge(
    bus_: EventBus = bus,
    manager: ConnectionManager = ws_manager,
) -> None:
    # A laggy browser must never backpressure a graph run: drop oldest.
    sub = bus_.subscribe("websocket", maxsize=1000, drop_oldest=True)
    try:
        while True:
            event = await sub.get()
            if not event.session_id:
                continue
            try:
                await manager.broadcast(event.session_id, {**event.payload, "seq": event.seq})
            except Exception:
                logger.exception("WS bridge send failed for %s", event.topic)
    finally:
        bus_.unsubscribe(sub)
