"""Durable event outbox — SQLite WAL log of every bus event (tokens excluded).

Gives the dashboard replay-on-reconnect (GET /api/v1/events?since=N) and makes
the event stream a queryable audit source instead of fire-and-forget frames.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

from core.bus.events import Event

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class EventOutbox:
    def __init__(self, db_path: str | Path | None = None):
        path = Path(db_path) if db_path else _DATA_DIR / "events.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = Lock()
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    thread_id TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL
                )
                """
            )

    def append(self, event: Event) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO events (seq, ts, topic, session_id, thread_id, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.seq,
                    event.ts,
                    event.topic,
                    event.session_id,
                    event.thread_id,
                    json.dumps(event.payload, default=str),
                ),
            )

    def max_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT MAX(seq) FROM events").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def read_since(self, seq: int, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, ts, topic, session_id, thread_id, payload FROM events "
                "WHERE seq > ? ORDER BY seq LIMIT ?",
                (seq, limit),
            ).fetchall()
        return self._rows_to_dicts(rows)

    def read_between(
        self,
        start_ts: str,
        end_ts: str,
        *,
        limit: int = 100_000,
    ) -> list[dict[str, Any]]:
        """Return events with ts in [start_ts, end_ts] (ISO-8601 strings, inclusive)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, ts, topic, session_id, thread_id, payload FROM events "
                "WHERE ts >= ? AND ts <= ? ORDER BY seq LIMIT ?",
                (start_ts, end_ts, limit),
            ).fetchall()
        return self._rows_to_dicts(rows)

    def read_by_thread_id(self, thread_id: str, *, limit: int = 10_000) -> list[dict[str, Any]]:
        """Return events for one LangGraph thread / correlation id, ordered by seq."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, ts, topic, session_id, thread_id, payload FROM events "
                "WHERE thread_id = ? ORDER BY seq LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        return self._rows_to_dicts(rows)

    @staticmethod
    def _rows_to_dicts(rows) -> list[dict[str, Any]]:
        out = []
        for r in rows:
            try:
                payload = json.loads(r[5])
            except json.JSONDecodeError:
                payload = {}
            out.append(
                {
                    "seq": r[0],
                    "ts": r[1],
                    "topic": r[2],
                    "session_id": r[3],
                    "thread_id": r[4],
                    "payload": payload,
                }
            )
        return out


_outbox: EventOutbox | None = None


def get_outbox() -> EventOutbox:
    global _outbox
    if _outbox is None:
        _outbox = EventOutbox()
    return _outbox
