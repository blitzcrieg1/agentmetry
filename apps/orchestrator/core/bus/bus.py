"""EventBus — synchronous publish, per-subscriber queues, explicit drop policy.

Loop-thread only: publish() must be called from the event loop (the vault
watcher already marshals via call_soon_threadsafe). Publishing never blocks —
each subscriber declares whether overflow drops its oldest events (WS bridge)
or is unbounded (outbox persister, which must never lose audit events).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from core.bus.events import Event

logger = logging.getLogger(__name__)


@dataclass
class Subscription:
    name: str
    queue: asyncio.Queue
    topics: frozenset[str] | None      # None = all topics
    exclude: frozenset[str]
    drop_oldest: bool

    async def get(self) -> Event:
        return await self.queue.get()


@dataclass
class EventBus:
    _subs: list[Subscription] = field(default_factory=list)
    _seq: int = 0

    def set_initial_seq(self, seq: int) -> None:
        """Continue numbering after the outbox's last persisted event."""
        self._seq = max(self._seq, seq)

    def subscribe(
        self,
        name: str,
        *,
        topics: set[str] | None = None,
        exclude: set[str] | None = None,
        maxsize: int = 0,
        drop_oldest: bool = False,
    ) -> Subscription:
        sub = Subscription(
            name=name,
            queue=asyncio.Queue(maxsize=maxsize),
            topics=frozenset(topics) if topics is not None else None,
            exclude=frozenset(exclude or ()),
            drop_oldest=drop_oldest,
        )
        self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs = [s for s in self._subs if s is not sub]

    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        session_id: str = "",
        thread_id: str = "",
    ) -> Event:
        self._seq += 1
        event = Event(
            topic=topic,
            payload=payload,
            seq=self._seq,
            session_id=session_id,
            thread_id=thread_id,
        )
        for sub in self._subs:
            if sub.topics is not None and topic not in sub.topics:
                continue
            if topic in sub.exclude:
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                if sub.drop_oldest:
                    try:
                        sub.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                    try:
                        sub.queue.put_nowait(event)
                    except asyncio.QueueFull:
                        pass
                else:
                    logger.warning("Bus subscriber %s full — dropped %s", sub.name, topic)
        return event


bus = EventBus()
