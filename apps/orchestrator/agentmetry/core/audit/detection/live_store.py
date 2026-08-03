"""SQLite checkpoint for live detection — survives orchestrator restarts.

Persists per-session event windows (bounded) and emitted rule IDs so a restart
does not re-fire detections or lose correlation context for active sessions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SESSIONS = 256
_MAX_EVENTS_PER_SESSION = 500

# How long a host-level detection stays suppressed after firing. Session marks
# are permanent (a session ends); host marks are not (a host does not), so
# without this a single firing silenced the rule on that machine forever.
HOST_EMIT_TTL_SECONDS = 6 * 3600


def _is_expired(emitted_at: str, *, ttl_seconds: int = HOST_EMIT_TTL_SECONDS) -> bool:
    """True when a host checkpoint is old enough to re-arm.

    An unparsable timestamp counts as expired: re-alerting is a smaller failure
    than a rule that is silently off.
    """
    try:
        ts = datetime.fromisoformat(emitted_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS live_session_meta (
    correlation_id TEXT PRIMARY KEY,
    last_touch     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS live_events (
    correlation_id TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    event_json     TEXT NOT NULL,
    PRIMARY KEY (correlation_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_live_events_corr ON live_events(correlation_id);

CREATE TABLE IF NOT EXISTS live_emitted (
    correlation_id TEXT NOT NULL,
    rule_id        TEXT NOT NULL,
    emitted_at     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (correlation_id, rule_id)
);

CREATE TABLE IF NOT EXISTS live_host_meta (
    host_id     TEXT PRIMARY KEY,
    last_touch  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS live_host_events (
    host_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    event_json  TEXT NOT NULL,
    PRIMARY KEY (host_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_live_host_events_host ON live_host_events(host_id);

CREATE TABLE IF NOT EXISTS live_host_emitted (
    host_id   TEXT NOT NULL,
    rule_id   TEXT NOT NULL,
    emitted_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (host_id, rule_id)
);
"""


class LiveDetectionStore:
    """Thread-safe SQLite store for live detection state."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def clear_all(self) -> None:
        """Test helper — wipe all live detection state."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM live_events")
            conn.execute("DELETE FROM live_emitted")
            conn.execute("DELETE FROM live_session_meta")
            conn.execute("DELETE FROM live_host_events")
            conn.execute("DELETE FROM live_host_emitted")
            conn.execute("DELETE FROM live_host_meta")
            conn.commit()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def append_event(self, correlation_id: str, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Append an event and return the bounded session window."""
        with self._lock:
            conn = self._get_conn()
            # Wall clock, not monotonic: last_touch is persisted, and monotonic
            # resets on reboot — pre-reboot sessions would outrank new ones and
            # LRU eviction would evict the newest sessions first.
            now = time.time()
            conn.execute(
                """
                INSERT INTO live_session_meta (correlation_id, last_touch)
                VALUES (?, ?)
                ON CONFLICT(correlation_id) DO UPDATE SET last_touch = excluded.last_touch
                """,
                (correlation_id, now),
            )
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM live_events WHERE correlation_id = ?",
                (correlation_id,),
            ).fetchone()
            next_seq = int(row[0]) + 1
            conn.execute(
                "INSERT INTO live_events (correlation_id, seq, event_json) VALUES (?, ?, ?)",
                (correlation_id, next_seq, json.dumps(event, separators=(",", ":"), sort_keys=True)),
            )
            min_seq = max(1, next_seq - _MAX_EVENTS_PER_SESSION + 1)
            conn.execute(
                "DELETE FROM live_events WHERE correlation_id = ? AND seq < ?",
                (correlation_id, min_seq),
            )
            self._evict_lru(conn)
            conn.commit()
            return self._load_events(conn, correlation_id)

    def _load_events(self, conn: sqlite3.Connection, correlation_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT event_json FROM live_events
            WHERE correlation_id = ?
            ORDER BY seq ASC
            """,
            (correlation_id,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for (raw,) in rows:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return events

    def _evict_lru(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) FROM live_session_meta").fetchone()[0]
        if count <= _MAX_SESSIONS:
            return
        overflow = count - _MAX_SESSIONS
        rows = conn.execute(
            """
            SELECT correlation_id FROM live_session_meta
            ORDER BY last_touch ASC
            LIMIT ?
            """,
            (overflow,),
        ).fetchall()
        for (corr,) in rows:
            conn.execute("DELETE FROM live_events WHERE correlation_id = ?", (corr,))
            conn.execute("DELETE FROM live_session_meta WHERE correlation_id = ?", (corr,))

    def is_emitted(self, correlation_id: str, rule_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """
                SELECT 1 FROM live_emitted
                WHERE correlation_id = ? AND rule_id = ?
                """,
                (correlation_id, rule_id),
            ).fetchone()
            return row is not None

    def mark_emitted(self, correlation_id: str, rule_id: str, emitted_at: str = "") -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT OR IGNORE INTO live_emitted (correlation_id, rule_id, emitted_at)
                VALUES (?, ?, ?)
                """,
                (correlation_id, rule_id, emitted_at),
            )
            conn.commit()

    def append_host_event(self, host_id: str, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Append an event to the host-level window and return bounded events."""
        if not host_id:
            return []
        with self._lock:
            conn = self._get_conn()
            now = time.time()
            conn.execute(
                """
                INSERT INTO live_host_meta (host_id, last_touch)
                VALUES (?, ?)
                ON CONFLICT(host_id) DO UPDATE SET last_touch = excluded.last_touch
                """,
                (host_id, now),
            )
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM live_host_events WHERE host_id = ?",
                (host_id,),
            ).fetchone()
            next_seq = int(row[0]) + 1
            conn.execute(
                "INSERT INTO live_host_events (host_id, seq, event_json) VALUES (?, ?, ?)",
                (host_id, next_seq, json.dumps(event, separators=(",", ":"), sort_keys=True)),
            )
            min_seq = max(1, next_seq - _MAX_EVENTS_PER_SESSION + 1)
            conn.execute(
                "DELETE FROM live_host_events WHERE host_id = ? AND seq < ?",
                (host_id, min_seq),
            )
            conn.commit()
            return self._load_host_events(conn, host_id)

    def _load_host_events(self, conn: sqlite3.Connection, host_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT event_json FROM live_host_events
            WHERE host_id = ?
            ORDER BY seq ASC
            """,
            (host_id,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for (raw,) in rows:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return events

    def is_host_emitted(self, host_id: str, rule_id: str) -> bool:
        """Has this host-level rule fired recently enough to stay suppressed?

        Host checkpoints expire; session ones do not. A session ends, so a
        permanent mark is correct there. A host does not: without an expiry the
        first firing — quite possibly a false positive — silenced the rule on
        that machine forever, and only deleting a SQLite row brought it back.
        A recorder that goes permanently blind after one alert is worse than one
        that occasionally repeats itself.
        """
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """
                SELECT emitted_at FROM live_host_emitted
                WHERE host_id = ? AND rule_id = ?
                """,
                (host_id, rule_id),
            ).fetchone()
            if row is None:
                return False
            emitted_at = str(row[0] or "")
            if not emitted_at:
                # Pre-expiry rows carry no usable timestamp. Treat them as stale
                # so an upgrade re-arms the rule instead of inheriting silence.
                conn.execute(
                    "DELETE FROM live_host_emitted WHERE host_id = ? AND rule_id = ?",
                    (host_id, rule_id),
                )
                conn.commit()
                return False
            if _is_expired(emitted_at):
                conn.execute(
                    "DELETE FROM live_host_emitted WHERE host_id = ? AND rule_id = ?",
                    (host_id, rule_id),
                )
                conn.commit()
                return False
            return True

    def mark_host_emitted(self, host_id: str, rule_id: str, emitted_at: str = "") -> None:
        """Checkpoint a host-level detection, refreshing the suppression clock.

        Upsert rather than INSERT OR IGNORE: the timestamp drives expiry, so a
        re-fire must move it forward or the rule would re-arm on the original
        schedule regardless of recent activity. An absent timestamp falls back to
        now, so a row always carries a usable clock.
        """
        stamp = emitted_at or datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """
                INSERT INTO live_host_emitted (host_id, rule_id, emitted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(host_id, rule_id) DO UPDATE SET emitted_at = excluded.emitted_at
                """,
                (host_id, rule_id, stamp),
            )
            conn.commit()


_store: LiveDetectionStore | None = None
_store_lock = threading.Lock()


def get_live_store() -> LiveDetectionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from agentmetry.core.config import settings

                _store = LiveDetectionStore(settings.detection_live_db_path)
    return _store


def reset_live_store_singleton() -> None:
    """Drop the singleton without deleting data — simulates process restart."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = None
