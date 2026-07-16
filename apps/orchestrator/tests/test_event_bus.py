"""Event bus: delivery, filtering, overflow policy, outbox durability, bridges."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from api.ws_bridge import ws_event_bridge
from core.bus.audit_exporter import audit_exporter
from core.bus.bridges import outbox_persister
from core.bus.bus import EventBus
from core.bus.events import LLM_TOKEN, RUN_COMPLETED, RUN_STARTED, Event
from core.bus.outbox import EventOutbox


def test_topic_filtering_and_exclusion():
    bus = EventBus()
    everything = bus.subscribe("all")
    runs_only = bus.subscribe("runs", topics={RUN_STARTED})
    no_tokens = bus.subscribe("quiet", exclude={LLM_TOKEN})

    bus.publish(RUN_STARTED, {"type": "execution_started"})
    bus.publish(LLM_TOKEN, {"type": "token"})

    assert everything.queue.qsize() == 2
    assert runs_only.queue.qsize() == 1
    assert no_tokens.queue.qsize() == 1
    assert no_tokens.queue.get_nowait().topic == RUN_STARTED


def test_seq_is_monotonic_and_resumes_from_outbox():
    bus = EventBus()
    bus.set_initial_seq(41)
    first = bus.publish(RUN_STARTED, {})
    second = bus.publish(RUN_COMPLETED, {})
    assert (first.seq, second.seq) == (42, 43)


def test_drop_oldest_keeps_newest():
    bus = EventBus()
    sub = bus.subscribe("ws", maxsize=2, drop_oldest=True)
    for i in range(4):
        bus.publish(RUN_STARTED, {"i": i})
    received = [sub.queue.get_nowait().payload["i"] for _ in range(2)]
    assert received == [2, 3]  # oldest evicted, newest preserved


def test_outbox_roundtrip(tmp_path: Path):
    outbox = EventOutbox(tmp_path / "events.db")
    assert outbox.max_seq() == 0

    outbox.append(Event(topic=RUN_STARTED, payload={"skill": "x"}, seq=1, thread_id="t1"))
    outbox.append(Event(topic=RUN_COMPLETED, payload={"cost": 0.1}, seq=2, thread_id="t1"))

    assert outbox.max_seq() == 2
    events = outbox.read_since(1)
    assert len(events) == 1
    assert events[0]["topic"] == RUN_COMPLETED
    assert events[0]["payload"] == {"cost": 0.1}


async def test_audit_exporter_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from core.config import settings

    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "audit-forward.jsonl")
    monkeypatch.setattr(settings, "audit_sink", "file")
    monkeypatch.setattr(settings, "audit_webhook_url", "")

    bus = EventBus()
    task = asyncio.create_task(audit_exporter(bus, enabled=True))
    await asyncio.sleep(0)

    bus.publish(RUN_STARTED, {"type": "execution_started", "skill": "x"}, thread_id="t1")
    bus.publish(LLM_TOKEN, {"type": "token"}, session_id="s1")
    await asyncio.sleep(0.05)
    task.cancel()

    export_path = tmp_path / "audit-forward.jsonl"
    lines = export_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    from core.audit.trail_chain import unwrap_trail_record

    assert unwrap_trail_record(json.loads(lines[0]))["action"]["type"] == "session_start"


async def test_persister_excludes_tokens(tmp_path: Path):
    bus = EventBus()
    outbox = EventOutbox(tmp_path / "events.db")
    task = asyncio.create_task(outbox_persister(bus, outbox))
    await asyncio.sleep(0)  # let it subscribe

    bus.publish(RUN_STARTED, {"type": "execution_started"}, thread_id="t1")
    bus.publish(LLM_TOKEN, {"type": "token"}, session_id="s1")
    await asyncio.sleep(0.05)
    task.cancel()

    rows = outbox.read_since(0)
    assert [r["topic"] for r in rows] == [RUN_STARTED]


class FakeManager:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def broadcast(self, session_id: str, payload: dict) -> None:
        self.sent.append((session_id, payload))


async def test_ws_bridge_forwards_payload_with_seq():
    bus = EventBus()
    manager = FakeManager()
    task = asyncio.create_task(ws_event_bridge(bus, manager))
    await asyncio.sleep(0)

    bus.publish(RUN_STARTED, {"type": "execution_started", "skill": "x"}, session_id="s1")
    bus.publish(RUN_COMPLETED, {"type": "execution_completed"})  # no session → not sent
    await asyncio.sleep(0.05)
    task.cancel()

    assert len(manager.sent) == 1
    session_id, payload = manager.sent[0]
    assert session_id == "s1"
    assert payload["type"] == "execution_started"  # wire format preserved
    assert payload["seq"] == 1                     # replay cursor attached
