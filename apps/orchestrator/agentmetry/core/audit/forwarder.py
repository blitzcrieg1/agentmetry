"""Forward the chained trail to SIEMs from a cursor (pilot hardening item 19).

Every network sink used to be called inline, once per event, with a fresh HTTP
client and no retry. A SIEM that was down for an hour lost an hour of events:
the local trail had them, the SIEM never would, and nothing recorded the gap.

The trail is already a durable, ordered, hash-chained log, so it is the queue.
Producers append to it and nothing else. One task per destination tails it
from a persisted cursor, sends batches, retries with exponential backoff and
jitter, and moves the cursor only after the destination accepted the batch.

Delivery is at-least-once. A crash between a send and the cursor write resends
that batch; Elastic (bulk `_id` = `event_id`) and the Enterprise console
(dedup on `event_id`) absorb that, Splunk and plain webhooks see a duplicate.
Nothing is skipped silently: an event a destination rejects as malformed (a
4xx that is not 408/429) is isolated, written to a dead-letter file beside the
cursor, and logged, so one bad event cannot wedge the feed forever.

The cursor names the last forwarded record by `seq` and `record_sha256`. On
resume the next record's `prev_sha256` must equal that hash, which the chain
guarantees; if it does not (the trail was replaced, restored or rotated), the
forwarder finds its place again by scanning for the record after it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

import httpx

from agentmetry.core.audit.trail_chain import is_chained_record

logger = logging.getLogger(__name__)

#: A batch never exceeds this many bytes of trail, whatever the event count.
#: The Enterprise console caps a request at 1 MiB; this stays under it.
DEFAULT_MAX_BATCH_BYTES = 900_000
DEFAULT_MAX_BACKOFF_SECONDS = 300.0
DEFAULT_POLL_SECONDS = 1.0


class ForwardError(Exception):
    """A destination did not accept a batch. `retryable` decides what happens next."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def raise_for(response: httpx.Response, target: str) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    retryable = status in (408, 425, 429) or status >= 500
    raise ForwardError(f"{target} answered HTTP {status}", retryable=retryable)


class Destination(Protocol):
    name: str
    max_batch: int

    async def send_batch(self, client: httpx.AsyncClient, events: list[dict[str, Any]]) -> None:
        ...

    def make_client(self) -> httpx.AsyncClient:
        """One long-lived client per destination, with that sink's TLS settings."""
        ...


# --- cursor ------------------------------------------------------------------


@dataclass
class Cursor:
    """The last record a destination accepted. `file` is a trail segment name."""

    file: str = ""
    offset: int = 0
    seq: int = 0
    sha256: str = ""
    forwarded: int = 0
    updated_utc: str = ""


def cursor_dir(trail_path: Path) -> Path:
    return trail_path.parent / "forward-cursors"


class CursorStore:
    def __init__(self, trail_path: Path, name: str) -> None:
        self.path = cursor_dir(trail_path) / f"{name}.json"
        self.deadletter = cursor_dir(trail_path) / f"{name}.deadletter.jsonl"

    def load(self) -> Cursor:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return Cursor(**{k: data[k] for k in Cursor.__dataclass_fields__ if k in data})
        except (OSError, ValueError, TypeError):
            return Cursor()

    def save(self, cursor: Cursor) -> None:
        cursor.updated_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(cursor), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def dead_letter(self, event: dict[str, Any], reason: str) -> None:
        self.deadletter.parent.mkdir(parents=True, exist_ok=True)
        with self.deadletter.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"reason": reason, "event": event}, default=str) + "\n")


# --- reading the trail -------------------------------------------------------


def trail_segments(trail_path: Path) -> list[Path]:
    """Every file of the trail, oldest first; the active file last."""
    try:
        from agentmetry.core.audit.trail_rotation import segments

        return segments(trail_path)
    except ImportError:
        return [trail_path]


class CursorMismatch(Exception):
    """The record after the cursor does not chain onto it."""


@dataclass
class Batch:
    events: list[dict[str, Any]] = field(default_factory=list)
    cursor: Cursor = field(default_factory=Cursor)


def _segment(trail_path: Path, cursor: Cursor) -> tuple[list[Path], int]:
    files = trail_segments(trail_path)
    names = [p.name for p in files]
    if not cursor.file:
        return files, 0
    if cursor.file not in names:
        raise CursorMismatch(f"segment {cursor.file} is no longer part of the trail")
    return files, names.index(cursor.file)


def read_batch(
    trail_path: Path,
    cursor: Cursor,
    *,
    max_events: int,
    max_bytes: int = DEFAULT_MAX_BATCH_BYTES,
) -> Batch:
    """Up to `max_events` events after `cursor`, and the cursor after them."""
    files, index = _segment(trail_path, cursor)
    out = Batch(cursor=Cursor(**asdict(cursor)))
    if not out.cursor.file:
        out.cursor.file = files[0].name
    size = 0
    first = True
    while index < len(files):
        path = files[index]
        try:
            length = path.stat().st_size
        except OSError:
            length = 0
        offset = out.cursor.offset if path.name == out.cursor.file else 0
        if offset > length:
            raise CursorMismatch(f"{path.name} is shorter than the cursor ({length} < {offset})")
        try:
            fh = path.open("rb")
        except OSError:
            break
        with fh:
            fh.seek(offset)
            while len(out.events) < max_events and size < max_bytes:
                raw = fh.readline()
                if not raw or not raw.endswith(b"\n"):
                    break  # caught up, or a writer is mid-line
                offset += len(raw)
                size += len(raw)
                text = raw.strip()
                if not text:
                    out.cursor.file, out.cursor.offset = path.name, offset
                    continue
                try:
                    record = json.loads(text)
                except ValueError:
                    logger.warning("Skipping unparseable trail line in %s at byte %d", path.name, offset - len(raw))
                    out.cursor.file, out.cursor.offset = path.name, offset
                    continue
                if is_chained_record(record):
                    trail = record["trail"]
                    if first and out.cursor.sha256 and trail.get("prev_sha256") != out.cursor.sha256:
                        raise CursorMismatch(
                            f"record seq {trail.get('seq')} does not chain onto forwarded seq {out.cursor.seq}"
                        )
                    out.cursor.seq = int(trail.get("seq") or 0)
                    out.cursor.sha256 = str(trail.get("record_sha256") or "")
                    event = record["event"]
                else:
                    event = record
                first = False
                out.events.append(event)
                out.cursor.file, out.cursor.offset = path.name, offset
        if len(out.events) >= max_events or size >= max_bytes:
            break
        if index + 1 < len(files) and out.cursor.offset >= length:
            # This segment is finished and a newer one exists: continue there.
            index += 1
            out.cursor.file, out.cursor.offset = files[index].name, 0
            continue
        break
    return out


def resync(trail_path: Path, cursor: Cursor) -> Cursor:
    """Find the cursor's place again after the trail changed underneath it.

    Looks for the forwarded record itself (by hash) and resumes after it. If it
    is gone, resumes before the first record with a higher `seq`. If the trail
    has nothing that recognisably follows, starts over: duplicates are a lesser
    failure than a gap.
    """
    for path in trail_segments(trail_path):
        offset = 0
        try:
            with path.open("rb") as fh:
                for raw in fh:
                    start = offset
                    offset += len(raw)
                    try:
                        record = json.loads(raw)
                    except ValueError:
                        continue
                    if not is_chained_record(record):
                        continue
                    trail = record["trail"]
                    if cursor.sha256 and trail.get("record_sha256") == cursor.sha256:
                        return Cursor(path.name, offset, cursor.seq, cursor.sha256, cursor.forwarded)
                    if int(trail.get("seq") or 0) > cursor.seq:
                        return Cursor(path.name, start, int(trail["seq"]) - 1, str(trail.get("prev_sha256") or ""),
                                      cursor.forwarded)
        except OSError:
            continue
    logger.error("Forward cursor at seq %d matches nothing in the trail; starting over", cursor.seq)
    return Cursor(forwarded=cursor.forwarded)


# --- the loop ----------------------------------------------------------------


def backoff_seconds(attempt: int, *, base: float = 1.0, cap: float = DEFAULT_MAX_BACKOFF_SECONDS) -> float:
    """Exponential with jitter: 1, 2, 4 ... seconds, capped, each scaled by 0.5 to 1.5."""
    delay = min(cap, base * (2 ** min(attempt - 1, 30)))
    return min(cap, delay * random.uniform(0.5, 1.5))  # noqa: S311 - jitter, not security


@dataclass
class ForwardState:
    """What `/api/v1/audit/status` reports per destination."""

    name: str
    seq: int = 0
    forwarded: int = 0
    dead_lettered: int = 0
    failing_since: float | None = None
    last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["failing_for_seconds"] = round(time.time() - self.failing_since, 1) if self.failing_since else 0.0
        return out


STATES: dict[str, ForwardState] = {}

Sleep = Callable[[float], Awaitable[None]]


class Forwarder:
    def __init__(
        self,
        destination: Destination,
        trail_path: Path,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    ) -> None:
        self.destination = destination
        self.trail_path = trail_path
        self.store = CursorStore(trail_path, destination.name)
        self.client = client
        self.sleep = sleep
        self.poll_seconds = poll_seconds
        self.max_backoff = max_backoff_seconds
        self.state = STATES.setdefault(destination.name, ForwardState(destination.name))

    async def _send_with_retry(self, client: httpx.AsyncClient, events: list[dict[str, Any]]) -> None:
        attempt = 0
        while True:
            try:
                await self.destination.send_batch(client, events)
                self.state.failing_since = None
                self.state.last_error = ""
                return
            except ForwardError as exc:
                if not exc.retryable:
                    await self._isolate(client, events, str(exc))
                    return
                error = str(exc)
            except httpx.HTTPError as exc:
                error = f"{type(exc).__name__}: {exc}"
            attempt += 1
            if self.state.failing_since is None:
                self.state.failing_since = time.time()
                logger.warning("Forwarding to %s failing (%s); retrying with backoff", self.destination.name, error)
            self.state.last_error = error
            await self.sleep(backoff_seconds(attempt, cap=self.max_backoff))

    async def _isolate(self, client: httpx.AsyncClient, events: list[dict[str, Any]], reason: str) -> None:
        """A rejected batch: find the event(s) the destination refuses, keep the rest."""
        if len(events) == 1:
            self.store.dead_letter(events[0], reason)
            self.state.dead_lettered += 1
            logger.error(
                "%s rejected event %s (%s); written to %s",
                self.destination.name, events[0].get("event_id", "?"), reason, self.store.deadletter,
            )
            return
        middle = len(events) // 2
        for half in (events[:middle], events[middle:]):
            await self._send_with_retry(client, half)

    async def step(self, client: httpx.AsyncClient) -> int:
        """Forward one batch if there is one. Returns how many events went."""
        cursor = self.store.load()
        try:
            batch = read_batch(self.trail_path, cursor, max_events=self.destination.max_batch)
        except CursorMismatch as exc:
            logger.warning("Forward cursor for %s: %s; resyncing", self.destination.name, exc)
            self.store.save(resync(self.trail_path, cursor))
            return 0
        if batch.events:
            await self._send_with_retry(client, batch.events)
            batch.cursor.forwarded = cursor.forwarded + len(batch.events)
        if asdict(batch.cursor) != asdict(cursor):
            self.store.save(batch.cursor)
        self.state.seq = batch.cursor.seq
        self.state.forwarded = batch.cursor.forwarded
        return len(batch.events)

    async def run(self) -> None:
        client = self.client or self.destination.make_client()
        try:
            while True:
                try:
                    sent = await self.step(client)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Forwarder %s step failed", self.destination.name)
                    sent = 0
                if not sent:
                    await self.sleep(self.poll_seconds)
        finally:
            if self.client is None:
                await client.aclose()


def forward_status() -> dict[str, dict[str, Any]]:
    return {name: state.as_dict() for name, state in STATES.items()}
