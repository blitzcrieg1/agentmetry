"""Core-side bus subscribers: durable persistence."""

from __future__ import annotations

import logging

from core.bus.bus import EventBus, bus
from core.bus.events import LLM_TOKEN
from core.bus.outbox import EventOutbox, get_outbox

logger = logging.getLogger(__name__)


async def outbox_persister(bus_: EventBus = bus, outbox: EventOutbox | None = None) -> None:
    """Persist every event except the token firehose. Never drops."""
    ob = outbox or get_outbox()
    sub = bus_.subscribe("outbox", exclude={LLM_TOKEN})
    try:
        while True:
            event = await sub.get()
            try:
                ob.append(event)
            except Exception:
                logger.exception("Outbox write failed for %s", event.topic)
    finally:
        bus_.unsubscribe(sub)
