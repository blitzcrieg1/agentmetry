"""SQLite WAL-backed audit event store.

Replaces the read-the-whole-JSONL-file-into-RAM pattern with indexed queries.
The JSONL sinks remain for SIEM forwarding; this module handles *queries*.

WAL mode gives concurrent readers + one writer without blocking — perfect for
the "one ingest writer, many dashboard readers" access pattern.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Legacy source names that should be normalized on read.
_LEGACY_SOURCE_APPS = frozenset({"blackbox"})

_RUN_ACTION_TYPES = frozenset({
    "session_start",
    "session_end",
    "tool_called",
    "approval_request",
    "approval_response",
    "detection",
})

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT UNIQUE NOT NULL,
    correlation_id  TEXT NOT NULL DEFAULT '',
    session_id      TEXT NOT NULL DEFAULT '',
    timestamp_utc   TEXT NOT NULL DEFAULT '',
    action_type     TEXT NOT NULL DEFAULT '',
    action_outcome  TEXT NOT NULL DEFAULT '',
    source_app      TEXT NOT NULL DEFAULT '',
    tool_qualified  TEXT NOT NULL DEFAULT '',
    event_json      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts      ON audit_events(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_events_corr    ON audit_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_events_source  ON audit_events(source_app);
CREATE INDEX IF NOT EXISTS idx_events_action  ON audit_events(action_type);
CREATE INDEX IF NOT EXISTS idx_events_session ON audit_events(session_id);
"""


def _normalize_source_app(name: str) -> str:
    return "agentmetry" if name in _LEGACY_SOURCE_APPS else name


def _extract_source_app(event: dict[str, Any]) -> str:
    source = event.get("source")
    if isinstance(source, dict) and source.get("app"):
        return _normalize_source_app(str(source["app"]).lower())
    agent = event.get("agent")
    if isinstance(agent, dict) and agent.get("name"):
        name = _normalize_source_app(str(agent["name"]).lower())
        if name != "agentmetry":
            return name
    return "agentmetry"


class AuditTrailDB:
    """Thread-safe SQLite WAL audit store."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        # Ensure the directory exists.
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        # Initialize schema on the calling thread.
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def insert(self, event: dict[str, Any]) -> None:
        """Insert a canonical event. Silently skips duplicates (UNIQUE on event_id)."""
        import uuid
        event_id = event.get("event_id", "")
        if not event_id:
            event_id = str(uuid.uuid4())
            event["event_id"] = event_id

        action = event.get("action") or {}
        tool = event.get("tool") or {}

        try:
            self._get_conn().execute(
                """INSERT OR IGNORE INTO audit_events
                   (event_id, correlation_id, session_id, timestamp_utc,
                    action_type, action_outcome, source_app, tool_qualified, event_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    str(event.get("correlation_id") or ""),
                    str(event.get("session_id") or ""),
                    str(event.get("timestamp_utc") or ""),
                    str(action.get("type") or ""),
                    str(action.get("outcome") or ""),
                    _extract_source_app(event),
                    str(tool.get("qualified") or ""),
                    json.dumps(event, default=str),
                ),
            )
            self._get_conn().commit()
        except sqlite3.Error as exc:
            logger.warning("trail_db insert failed: %s", exc)

    def insert_batch(self, events: list[dict[str, Any]]) -> int:
        """Bulk insert for migration. Returns rows ACTUALLY inserted.

        Counted via total_changes rather than attempts: INSERT OR IGNORE skips
        duplicates, so counting loop iterations overstates the result and made
        the backfill log claim work it had not done.
        """
        import uuid
        conn = self._get_conn()
        before = conn.total_changes
        for event in events:
            event_id = event.get("event_id", "")
            if not event_id:
                event_id = str(uuid.uuid4())
                event["event_id"] = event_id
            action = event.get("action") or {}
            tool = event.get("tool") or {}
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO audit_events
                       (event_id, correlation_id, session_id, timestamp_utc,
                        action_type, action_outcome, source_app, tool_qualified, event_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        event_id,
                        str(event.get("correlation_id") or ""),
                        str(event.get("session_id") or ""),
                        str(event.get("timestamp_utc") or ""),
                        str(action.get("type") or ""),
                        str(action.get("outcome") or ""),
                        _extract_source_app(event),
                        str(tool.get("qualified") or ""),
                        json.dumps(event, default=str),
                    ),
                )
            except sqlite3.Error:
                continue
        conn.commit()
        return conn.total_changes - before

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def tail(
        self,
        *,
        limit: int = 50,
        scope: Literal["runs", "all"] = "runs",
        sources: set[str] | None = None,
        session_id: str | None = None,
        since_minutes: int | None = None,
        before_utc: str | None = None,
        after_utc: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Query the tail of the audit trail with filters and pagination."""
        clauses: list[str] = []
        params: list[Any] = []

        if scope == "runs":
            placeholders = ",".join("?" for _ in _RUN_ACTION_TYPES)
            clauses.append(f"action_type IN ({placeholders})")
            params.extend(_RUN_ACTION_TYPES)

        if sources:
            placeholders = ",".join("?" for _ in sources)
            clauses.append(f"source_app IN ({placeholders})")
            params.extend(sources)

        if session_id:
            clauses.append("(session_id = ? OR source_app != 'agentmetry')")
            params.append(session_id)

        if since_minutes is not None and since_minutes > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=since_minutes)).isoformat()
            clauses.append("timestamp_utc >= ?")
            params.append(cutoff)

        if before_utc and after_utc:
            raise ValueError("Use only one of before_utc or after_utc")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        conn = self._get_conn()

        if before_utc:
            sql = f"""SELECT event_json FROM audit_events {where}
                      {"AND" if clauses else "WHERE"} timestamp_utc < ?
                      ORDER BY timestamp_utc DESC, id DESC LIMIT ?"""
            params.extend([before_utc, limit + 1])
            rows = conn.execute(sql, params).fetchall()
            has_older = len(rows) > limit
            page_rows = list(reversed(rows[:limit]))
            has_newer = True
        elif after_utc:
            sql = f"""SELECT event_json FROM audit_events {where}
                      {"AND" if clauses else "WHERE"} timestamp_utc > ?
                      ORDER BY timestamp_utc ASC, id ASC LIMIT ?"""
            params.extend([after_utc, limit + 1])
            rows = conn.execute(sql, params).fetchall()
            has_newer = len(rows) > limit
            page_rows = rows[:limit]
            has_older = True
        else:
            # Latest page: get last N rows
            sql = f"""SELECT event_json FROM audit_events {where}
                      ORDER BY timestamp_utc DESC, id DESC LIMIT ?"""
            params.append(limit + 1)
            rows = conn.execute(sql, params).fetchall()
            has_older = len(rows) > limit
            page_rows = list(reversed(rows[:limit]))
            has_newer = False

        events = []
        for row in page_rows:
            try:
                events.append(json.loads(row["event_json"]))
            except (json.JSONDecodeError, KeyError):
                continue

        pagination = {
            "has_older": has_older,
            "has_newer": has_newer,
            "oldest_utc": events[0].get("timestamp_utc") if events else None,
            "newest_utc": events[-1].get("timestamp_utc") if events else None,
            "count": len(events),
        }
        return events, pagination

    def session(self, correlation_id: str, limit: int = 2000) -> list[dict[str, Any]]:
        """Return all events for one correlation_id, time-ordered."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT event_json FROM audit_events
               WHERE correlation_id = ?
               ORDER BY timestamp_utc ASC, id ASC
               LIMIT ?""",
            (correlation_id, limit),
        ).fetchall()
        events = []
        for row in rows:
            try:
                events.append(json.loads(row["event_json"]))
            except (json.JSONDecodeError, KeyError):
                continue
        return events

    def events_for_detection(self, correlation_id: str) -> list[dict[str, Any]]:
        """Return events for detection correlation — no limit, full session."""
        return self.session(correlation_id, limit=10000)

    def status(self) -> dict[str, Any]:
        """Freshness + per-source counts for the dashboard badge."""
        conn = self._get_conn()

        # Per-source counts from recent events (last 500 by id)
        rows = conn.execute(
            """SELECT source_app, COUNT(*) as cnt
               FROM (SELECT source_app FROM audit_events ORDER BY id DESC LIMIT 500)
               GROUP BY source_app"""
        ).fetchall()
        by_source = {row["source_app"]: row["cnt"] for row in rows}

        # Last event timestamp
        row = conn.execute(
            "SELECT MAX(timestamp_utc) as last_ts FROM audit_events"
        ).fetchone()
        last_ts = row["last_ts"] if row else None

        # Total recent count
        row2 = conn.execute(
            "SELECT COUNT(*) as cnt FROM (SELECT 1 FROM audit_events ORDER BY id DESC LIMIT 500)"
        ).fetchone()
        recent = row2["cnt"] if row2 else 0

        return {
            "last_event_utc": last_ts,
            "recent": recent,
            "by_source": by_source,
        }

    def stats(self, window_days: int = 7) -> dict[str, Any]:
        """Aggregate audit metrics for dogfood / operator dashboards."""
        days = max(1, min(window_days, 90))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        conn = self._get_conn()

        def _scalar(sql: str, *params: Any) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        total = _scalar(
            "SELECT COUNT(*) FROM audit_events WHERE timestamp_utc >= ?",
            cutoff,
        )
        sessions = _scalar(
            """SELECT COUNT(DISTINCT correlation_id) FROM audit_events
               WHERE timestamp_utc >= ? AND correlation_id != ''""",
            cutoff,
        )
        detections = _scalar(
            """SELECT COUNT(*) FROM audit_events
               WHERE timestamp_utc >= ? AND action_type = 'detection'""",
            cutoff,
        )
        denied = _scalar(
            """SELECT COUNT(*) FROM audit_events
               WHERE timestamp_utc >= ? AND action_outcome = 'denied'""",
            cutoff,
        )
        dlp_matches = _scalar(
            """SELECT COUNT(*) FROM audit_events
               WHERE timestamp_utc >= ?
                 AND json_extract(event_json, '$.dlp.rule_id') IS NOT NULL""",
            cutoff,
        )
        tool_policy_hits = _scalar(
            """SELECT COUNT(*) FROM audit_events
               WHERE timestamp_utc >= ?
                 AND json_extract(event_json, '$.tool_policy.rule_id') IS NOT NULL""",
            cutoff,
        )
        tool_policy_blocks = _scalar(
            """SELECT COUNT(*) FROM audit_events
               WHERE timestamp_utc >= ?
                 AND json_extract(event_json, '$.tool_policy.blocked') = 1""",
            cutoff,
        )

        rows = conn.execute(
            """SELECT source_app, COUNT(*) as cnt FROM audit_events
               WHERE timestamp_utc >= ?
               GROUP BY source_app
               ORDER BY cnt DESC""",
            (cutoff,),
        ).fetchall()
        by_source = {row["source_app"]: row["cnt"] for row in rows}

        last_row = conn.execute(
            "SELECT MAX(timestamp_utc) as last_ts FROM audit_events WHERE timestamp_utc >= ?",
            (cutoff,),
        ).fetchone()
        last_ts = last_row["last_ts"] if last_row else None

        return {
            "window_days": days,
            "total_events": total,
            "sessions": sessions,
            "detections": detections,
            "denied": denied,
            "dlp_matches": dlp_matches,
            "tool_policy_hits": tool_policy_hits,
            "tool_policy_blocks": tool_policy_blocks,
            "by_source": by_source,
            "last_event_utc": last_ts,
        }

    def count(self) -> int:
        """Total event count."""
        row = self._get_conn().execute("SELECT COUNT(*) as cnt FROM audit_events").fetchone()
        return row["cnt"] if row else 0


# ---------------------------------------------------------------------------
# Module-level singleton — lazily created from settings.
# ---------------------------------------------------------------------------

_db: AuditTrailDB | None = None
# Guards singleton creation: check-then-set on a global is a race, and the
# backfill runs in a worker thread while requests are already being served.
_db_lock = threading.Lock()


def get_trail_db() -> AuditTrailDB:
    """Return the module-level trail DB singleton, creating it on first call."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:  # re-check: another thread may have won the race
                from core.config import settings

                _db = AuditTrailDB(settings.audit_db_path)
    return _db


def reset_trail_db() -> None:
    """Test helper — clear the singleton."""
    global _db
    with _db_lock:
        _db = None
