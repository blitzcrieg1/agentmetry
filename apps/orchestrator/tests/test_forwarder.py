"""The trail forwarder (pilot hardening item 19).

Network sinks were called inline, once per event, with a fresh client and no
retry, so a SIEM outage lost every event it spanned. The acceptance bar from
the pilot brief: no events lost across a simulated four-hour Splunk or console
outage. The outage here runs on a virtual clock, so it takes milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentmetry.core.audit import forwarder as fw
from agentmetry.core.audit.sinks import (
    ElasticEcsSink,
    FileAuditSink,
    SplunkHecSink,
    WebhookAuditSink,
    build_production_sink,
    forward_destinations,
)
from agentmetry.core.audit.trail_chain import append_chained_line

FOUR_HOURS = 4 * 3600


def _event(n: int) -> dict[str, Any]:
    return {
        "event_id": f"evt-{n:05d}",
        "correlation_id": "sess-1",
        "timestamp_utc": "2026-10-03T10:00:00+00:00",
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
        "tool": {"qualified": "Bash", "name": "Bash"},
    }


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.on_tick: list = []

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        for hook in self.on_tick:
            hook()


class FakeSiem:
    """Accepts batches unless it is down; can refuse named events as malformed."""

    name = "splunk"
    max_batch = 50

    def __init__(self, clock: Clock, *, down_until: float = 0.0, poison: set[str] | None = None) -> None:
        self.clock = clock
        self.down_until = down_until
        self.poison = poison or set()
        self.received: list[str] = []
        self.attempts = 0

    def make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient()

    async def send_batch(self, client, events):
        self.attempts += 1
        if self.clock.now < self.down_until:
            raise fw.ForwardError("HTTP 503", retryable=True)
        if any(e["event_id"] in self.poison for e in events):
            raise fw.ForwardError("HTTP 400", retryable=False)
        self.received.extend(e["event_id"] for e in events)


@pytest.fixture
def trail(tmp_path: Path) -> Path:
    return tmp_path / "audit-forward.jsonl"


def _append(trail: Path, start: int, count: int) -> list[str]:
    ids = []
    for n in range(start, start + count):
        append_chained_line(trail, _event(n))
        ids.append(f"evt-{n:05d}")
    return ids


async def _drain(forwarder: fw.Forwarder, client) -> None:
    """Step until two in a row send nothing (a resync step sends nothing by design)."""
    idle = 0
    while idle < 2:
        idle = 0 if await forwarder.step(client) else idle + 1


# --- the acceptance test -----------------------------------------------------


async def test_no_event_is_lost_across_a_four_hour_outage(trail: Path):
    clock = Clock()
    siem = FakeSiem(clock, down_until=FOUR_HOURS)
    written = _append(trail, 0, 20)

    # Agents keep working while the SIEM is down: every backoff tick, more
    # events land in the trail.
    counter = {"n": 20}

    def traffic() -> None:
        written.extend(_append(trail, counter["n"], 3))
        counter["n"] += 3

    clock.on_tick.append(traffic)
    forwarder = fw.Forwarder(siem, trail, sleep=clock.sleep)
    async with httpx.AsyncClient() as client:
        await forwarder.step(client)  # blocks in retry for the whole outage
        assert clock.now >= FOUR_HOURS
        clock.on_tick.clear()
        await _drain(forwarder, client)

    assert siem.received == written, "every event, in trail order, nothing missing"
    assert len(written) > 100, "the outage must actually have spanned traffic"
    # Backoff is capped at five minutes, so four hours is dozens of attempts, not thousands.
    assert siem.attempts < 200


async def test_a_restart_in_the_middle_of_an_outage_loses_nothing(trail: Path):
    clock = Clock()
    siem = FakeSiem(clock, down_until=FOUR_HOURS)
    written = _append(trail, 0, 120)

    first = fw.Forwarder(siem, trail, sleep=clock.sleep)
    siem.down_until = 0
    async with httpx.AsyncClient() as client:
        await first.step(client)  # one batch of 50 delivered, then the process dies
        siem.down_until = clock.now + FOUR_HOURS
        written += _append(trail, 120, 30)
        second = fw.Forwarder(siem, trail, sleep=clock.sleep)  # a fresh process, same cursor
        await _drain(second, client)

    assert siem.received == written


async def test_the_cursor_is_written_only_after_the_siem_accepts(trail: Path):
    clock = Clock()
    siem = FakeSiem(clock)
    _append(trail, 0, 3)
    forwarder = fw.Forwarder(siem, trail, sleep=clock.sleep)
    async with httpx.AsyncClient() as client:
        await forwarder.step(client)
    cursor = forwarder.store.load()
    assert cursor.seq == 3
    assert cursor.forwarded == 3
    assert cursor.sha256, "the cursor names the last record by hash"


async def test_a_resumed_forwarder_sends_only_what_is_new(trail: Path):
    clock = Clock()
    siem = FakeSiem(clock)
    _append(trail, 0, 3)
    async with httpx.AsyncClient() as client:
        await fw.Forwarder(siem, trail, sleep=clock.sleep).step(client)
        _append(trail, 3, 2)
        await _drain(fw.Forwarder(siem, trail, sleep=clock.sleep), client)
    assert siem.received == [f"evt-{n:05d}" for n in range(5)]


# --- a bad event must not wedge the feed -------------------------------------


async def test_a_rejected_event_is_dead_lettered_and_the_rest_flow(trail: Path):
    clock = Clock()
    siem = FakeSiem(clock, poison={"evt-00007"})
    _append(trail, 0, 20)
    forwarder = fw.Forwarder(siem, trail, sleep=clock.sleep)
    async with httpx.AsyncClient() as client:
        await _drain(forwarder, client)
    assert "evt-00007" not in siem.received
    assert sorted(siem.received) == [f"evt-{n:05d}" for n in range(20) if n != 7]
    dead = [json.loads(line) for line in forwarder.store.deadletter.read_text(encoding="utf-8").splitlines()]
    assert [d["event"]["event_id"] for d in dead] == ["evt-00007"]
    assert forwarder.state.dead_lettered == 1


# --- the cursor and the chain ------------------------------------------------


async def test_a_replaced_trail_is_resynced_not_skipped(trail: Path):
    """Restored from backup or swapped: duplicates are acceptable, a gap is not."""
    clock = Clock()
    siem = FakeSiem(clock)
    _append(trail, 0, 5)
    async with httpx.AsyncClient() as client:
        await _drain(fw.Forwarder(siem, trail, sleep=clock.sleep), client)
        trail.unlink()
        trail.with_name(trail.name + ".chain").unlink(missing_ok=True)
        for sidecar in trail.parent.glob("*.chain*"):
            sidecar.unlink()
        _append(trail, 100, 3)
        await _drain(fw.Forwarder(siem, trail, sleep=clock.sleep), client)
    assert siem.received[-3:] == ["evt-00100", "evt-00101", "evt-00102"]


def test_read_batch_stops_at_a_half_written_line(trail: Path):
    _append(trail, 0, 2)
    with trail.open("a", encoding="utf-8") as fh:
        fh.write('{"trail": {"seq": 3')
    batch = fw.read_batch(trail, fw.Cursor(), max_events=10)
    assert [e["event_id"] for e in batch.events] == ["evt-00000", "evt-00001"]


def test_read_batch_respects_its_limits(trail: Path):
    _append(trail, 0, 10)
    assert len(fw.read_batch(trail, fw.Cursor(), max_events=4).events) == 4
    assert len(fw.read_batch(trail, fw.Cursor(), max_events=100, max_bytes=1).events) == 1


def test_a_cursor_that_does_not_chain_is_a_mismatch(trail: Path):
    _append(trail, 0, 3)
    first = fw.read_batch(trail, fw.Cursor(), max_events=1)
    forged = fw.Cursor(**{**first.cursor.__dict__, "sha256": "0" * 64})
    with pytest.raises(fw.CursorMismatch):
        fw.read_batch(trail, forged, max_events=10)


# --- retry policy ------------------------------------------------------------


@pytest.mark.parametrize(("status", "retryable"), [(500, True), (503, True), (429, True), (408, True),
                                                   (400, False), (401, False), (413, False)])
def test_which_failures_are_retried(status: int, retryable: bool):
    with pytest.raises(fw.ForwardError) as exc:
        fw.raise_for(httpx.Response(status), "siem")
    assert exc.value.retryable is retryable


def test_backoff_grows_and_is_capped():
    for attempt in range(1, 40):
        delay = fw.backoff_seconds(attempt, cap=300)
        assert 0 < delay <= 300
    assert fw.backoff_seconds(1, cap=300) <= 1.5


# --- the destinations' wire formats ------------------------------------------


def _capture() -> tuple[list[httpx.Request], httpx.AsyncClient]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"errors": False, "items": []})

    return seen, httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_splunk_sends_one_request_for_many_events():
    seen, client = _capture()
    sink = SplunkHecSink("https://splunk.example:8088", "tok")
    async with client:
        await sink.send_batch(client, [_event(1), _event(2), _event(3)])
    assert len(seen) == 1
    assert seen[0].content.count(b'"event"') >= 3


async def test_elastic_bulk_uses_the_event_id_so_a_resend_overwrites():
    seen, client = _capture()
    sink = ElasticEcsSink("https://es.example", "agentmetry", "key")
    async with client:
        await sink.send_batch(client, [_event(1), _event(2)])
    assert seen[0].url.path == "/_bulk"
    actions = [json.loads(line) for line in seen[0].content.decode().splitlines()[0::2]]
    assert [a["index"]["_id"] for a in actions] == ["evt-00001", "evt-00002"]


async def test_an_elastic_item_error_is_classified():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": True, "items": [{"index": {"status": 429, "error": {}}}]})

    sink = ElasticEcsSink("https://es.example", "agentmetry", "key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(fw.ForwardError) as exc:
            await sink.send_batch(client, [_event(1)])
    assert exc.value.retryable


async def test_the_console_gets_one_batched_request():
    seen, client = _capture()
    sink = WebhookAuditSink("https://console.example/ingest/v1/events", format="batch", token="t")
    async with client:
        await sink.send_batch(client, [_event(1), _event(2)])
    assert len(seen) == 1
    assert [e["event_id"] for e in json.loads(seen[0].content)["events"]] == ["evt-00001", "evt-00002"]
    assert seen[0].headers["authorization"] == "Bearer t"


async def test_a_plain_webhook_keeps_one_event_per_request():
    """Existing consumers must not see their payload shape change."""
    seen, client = _capture()
    sink = WebhookAuditSink("https://hook.example/")
    async with client:
        await sink.send_batch(client, [_event(1), _event(2)])
    assert [json.loads(r.content)["event_id"] for r in seen] == ["evt-00001", "evt-00002"]


# --- wiring ------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides):
    from agentmetry.core.config import settings

    values = dict(
        audit_sink="splunk", audit_export_path=tmp_path / "audit-forward.jsonl",
        audit_splunk_hec_url="https://splunk.example:8088", audit_splunk_hec_token="tok",
        audit_forwarder=True,
    )
    values.update(overrides)
    return settings.model_copy(update=values)


def test_producers_write_only_the_trail_when_forwarding(tmp_path: Path):
    sink = build_production_sink(_settings(tmp_path))
    assert isinstance(sink, FileAuditSink), "the trail is the queue, even with only a network mode set"


def test_the_inline_path_is_still_available(tmp_path: Path):
    sink = build_production_sink(_settings(tmp_path, audit_forwarder=False))
    assert isinstance(sink, SplunkHecSink)


def test_destinations_come_from_the_same_settings(tmp_path: Path):
    names = [d.name for d in forward_destinations(_settings(tmp_path, audit_sink="file,splunk"))]
    assert names == ["splunk"]
    assert forward_destinations(_settings(tmp_path, audit_sink="file")) == []


def test_status_reports_lag_and_failure(trail: Path):
    state = fw.STATES.setdefault("status-probe", fw.ForwardState("status-probe"))
    state.failing_since = 0.0
    assert "failing_for_seconds" in fw.forward_status()["status-probe"]
    del fw.STATES["status-probe"]


# --- replay reads the trail --------------------------------------------------


def test_replay_finds_hook_events_in_the_trail(trail: Path):
    from agentmetry.core.audit.replay import format_timeline, read_trail_events

    _append(trail, 0, 3)
    append_chained_line(trail, {**_event(9), "correlation_id": "someone-else"})
    rows = read_trail_events(trail, "sess-1")
    assert len(rows) == 3
    text = format_timeline(rows, thread_id="sess-1")
    assert "3 event(s)" in text and "tool=Bash" in text
