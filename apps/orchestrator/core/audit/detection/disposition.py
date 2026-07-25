"""Detection triage — what the human decided, and when.

Until now Agentmetry recorded findings and stopped. That is half a control: a
detection nobody dispositioned is an alert, not evidence. ISO/IEC 42001 cl. 10
and EN 18286 cl. 8 both ask for the corrective action, not just the observation,
and the compliance digest was already asking for a triage note the product had
nowhere to store.

Two rules shape this module.

**The decision is an event.** Every disposition change is appended to the
canonical trail as an `action.type = "detection_disposition"` event, so it lands
on the same hash chain as the finding it answers and forwards to the same SIEM.
The table below is a materialized view of those events, not the system of
record — `rebuild_from_trail` regenerates it, which is the same recomputable
property the rest of the product has.

**History is append-only.** A disposition is never edited or deleted, only
superseded. "It was a false positive" changing to "actually it was real" is
exactly the transition an auditor cares about, so both entries survive.

A detection has no database id: rules are recomputed from events on demand. Its
stable identity is the pair the live checkpoint already uses, the scope it fired
in and the rule that fired, which is what `detection_key` builds.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DISPOSITION_EVENT_TYPE = "detection_disposition"

#: Triage states, in the order they appear in the dashboard.
STATUSES: tuple[str, ...] = (
    "new",
    "acknowledged",
    "in_progress",
    "resolved",
    "false_positive",
    "risk_accepted",
)

DEFAULT_STATUS = "new"

#: States that close a finding without confirming it. An auditor will ask why,
#: so the product asks first: a bare "false positive" is not a disposition, it
#: is a dismissal wearing one.
_NOTE_REQUIRED = frozenset({"false_positive", "risk_accepted"})

#: States that mean no further action is expected.
CLOSED_STATUSES = frozenset({"resolved", "false_positive", "risk_accepted"})

_MAX_NOTE_CHARS = 4000
_MAX_ASSIGNEE_CHARS = 128

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS detection_dispositions (
    detection_key   TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL DEFAULT '',
    rule_id         TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'new',
    assignee        TEXT NOT NULL DEFAULT '',
    note            TEXT NOT NULL DEFAULT '',
    decided_by      TEXT NOT NULL DEFAULT '',
    decided_at_utc  TEXT NOT NULL DEFAULT '',
    first_seen_utc  TEXT NOT NULL DEFAULT '',
    event_id        TEXT NOT NULL DEFAULT '',
    history_json    TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_disp_status ON detection_dispositions(status);
CREATE INDEX IF NOT EXISTS idx_disp_corr   ON detection_dispositions(correlation_id);
CREATE INDEX IF NOT EXISTS idx_disp_rule   ON detection_dispositions(rule_id);
"""


class DispositionError(ValueError):
    """Rejected disposition — surfaced to the caller as a 400, not a 500."""


def detection_key(correlation_id: str, rule_id: str) -> str:
    """Stable identity for a detection across recomputations.

    Rules are re-run over the trail rather than stored, so the key is the scope
    plus the rule, matching the pair `mark_detection_emitted` checkpoints on.
    Host-level rules carry their host in `correlation_id` already.
    """
    corr = (correlation_id or "").strip()
    rule = (rule_id or "").strip()
    if not rule:
        raise DispositionError("rule_id is required")
    return f"{corr}::{rule}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(status: str, note: str) -> tuple[str, str]:
    normalized = (status or "").strip().lower()
    if normalized not in STATUSES:
        raise DispositionError(
            f"unknown status {status!r}; expected one of {', '.join(STATUSES)}"
        )
    clean_note = (note or "").strip()
    if len(clean_note) > _MAX_NOTE_CHARS:
        raise DispositionError(f"note exceeds {_MAX_NOTE_CHARS} characters")
    if normalized in _NOTE_REQUIRED and not clean_note:
        raise DispositionError(
            f"status {normalized!r} requires a note explaining the decision"
        )
    return normalized, clean_note


class DispositionStore:
    """Thread-safe SQLite store for current triage state."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        correlation_id: str,
        rule_id: str,
        status: str,
        assignee: str = "",
        note: str = "",
        decided_by: str = "",
        decided_at_utc: str = "",
        event_id: str = "",
    ) -> dict[str, Any]:
        """Upsert current state and append to this detection's history."""
        normalized, clean_note = _validate(status, note)
        key = detection_key(correlation_id, rule_id)
        decided_at = decided_at_utc or _now()
        clean_assignee = (assignee or "").strip()[:_MAX_ASSIGNEE_CHARS]

        conn = self._get_conn()
        row = conn.execute(
            "SELECT history_json, first_seen_utc FROM detection_dispositions "
            "WHERE detection_key = ?",
            (key,),
        ).fetchone()
        history: list[dict[str, Any]] = []
        first_seen = decided_at
        if row is not None:
            try:
                history = json.loads(row["history_json"]) or []
            except (json.JSONDecodeError, TypeError):
                history = []
            first_seen = row["first_seen_utc"] or decided_at

        history.append({
            "status": normalized,
            "assignee": clean_assignee,
            "note": clean_note,
            "decided_by": decided_by.strip(),
            "decided_at_utc": decided_at,
            "event_id": event_id,
        })

        conn.execute(
            """INSERT INTO detection_dispositions
               (detection_key, correlation_id, rule_id, status, assignee, note,
                decided_by, decided_at_utc, first_seen_utc, event_id, history_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(detection_key) DO UPDATE SET
                 status         = excluded.status,
                 assignee       = excluded.assignee,
                 note           = excluded.note,
                 decided_by     = excluded.decided_by,
                 decided_at_utc = excluded.decided_at_utc,
                 event_id       = excluded.event_id,
                 history_json   = excluded.history_json""",
            (
                key,
                (correlation_id or "").strip(),
                rule_id.strip(),
                normalized,
                clean_assignee,
                clean_note,
                decided_by.strip(),
                decided_at,
                first_seen,
                event_id,
                json.dumps(history),
            ),
        )
        conn.commit()
        return self.get(correlation_id, rule_id) or {}

    def clear(self) -> None:
        """Test helper — drop all triage state."""
        conn = self._get_conn()
        conn.execute("DELETE FROM detection_dispositions")
        conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, correlation_id: str, rule_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM detection_dispositions WHERE detection_key = ?",
            (detection_key(correlation_id, rule_id),),
        ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def for_correlation(self, correlation_id: str) -> dict[str, dict[str, Any]]:
        """Current state for one session, keyed by rule_id."""
        rows = self._get_conn().execute(
            "SELECT * FROM detection_dispositions WHERE correlation_id = ?",
            ((correlation_id or "").strip(),),
        ).fetchall()
        return {str(row["rule_id"]): _row_to_dict(row) for row in rows}

    def all(self) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM detection_dispositions ORDER BY decided_at_utc DESC"
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        rows = self._get_conn().execute(
            "SELECT status, COUNT(*) AS n FROM detection_dispositions GROUP BY status"
        ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        history = json.loads(row["history_json"]) or []
    except (json.JSONDecodeError, TypeError):
        history = []
    return {
        "detection_key": row["detection_key"],
        "correlation_id": row["correlation_id"],
        "rule_id": row["rule_id"],
        "status": row["status"],
        "assignee": row["assignee"],
        "note": row["note"],
        "decided_by": row["decided_by"],
        "decided_at_utc": row["decided_at_utc"],
        "first_seen_utc": row["first_seen_utc"],
        "event_id": row["event_id"],
        "history": history,
        "closed": row["status"] in CLOSED_STATUSES,
    }


# ---------------------------------------------------------------------------
# Canonical event
# ---------------------------------------------------------------------------

def build_disposition_event(
    *,
    correlation_id: str,
    rule_id: str,
    status: str,
    assignee: str = "",
    note: str = "",
    decided_by: str = "",
    previous_status: str = DEFAULT_STATUS,
    severity: str = "",
) -> dict[str, Any]:
    """Wrap a triage decision as a canonical event.

    `action.outcome` carries the new status so a SIEM can alert on
    `action.type:detection_disposition AND action.outcome:risk_accepted`
    without understanding Agentmetry's vocabulary. The note is operator-written
    text, never captured command content, so it is safe to forward.
    """
    from core.config import settings

    return {
        "schema_version": "1.1.0",
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "session_id": "",
        "timestamp_utc": _now(),
        "source_topic": f"disposition/{rule_id}",
        "source": {"tier": "detection", "app": "agentmetry"},
        "actor": {"id": decided_by or settings.operator_id, "type": "human"},
        "initiator": {"type": "human", "id": decided_by or settings.operator_id},
        "action": {
            "type": DISPOSITION_EVENT_TYPE,
            "outcome": status,
            "reason": note or f"disposition set to {status}",
        },
        "agent": {"name": "agentmetry"},
        "disposition": {
            "detection_key": detection_key(correlation_id, rule_id),
            "rule_id": rule_id,
            "severity": severity,
            "status": status,
            "previous_status": previous_status,
            "assignee": assignee,
            "note": note,
            "decided_by": decided_by or settings.operator_id,
        },
    }


def extract_dispositions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pull disposition decisions out of a canonical event list, oldest first."""
    found: list[dict[str, Any]] = []
    for event in events:
        action = event.get("action") or {}
        if action.get("type") != DISPOSITION_EVENT_TYPE:
            continue
        disposition = event.get("disposition")
        if not isinstance(disposition, dict):
            continue
        found.append({
            "ts": event.get("timestamp_utc"),
            "correlation_id": event.get("correlation_id"),
            **{
                k: disposition.get(k)
                for k in (
                    "detection_key",
                    "rule_id",
                    "severity",
                    "status",
                    "previous_status",
                    "assignee",
                    "note",
                    "decided_by",
                )
            },
        })
    return found


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_store: DispositionStore | None = None
_store_lock = threading.Lock()


def get_disposition_store() -> DispositionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from core.config import settings

                _store = DispositionStore(settings.detection_disposition_db_path)
    return _store


def reset_disposition_store() -> None:
    """Test helper — drop the singleton so a new path takes effect."""
    global _store
    _store = None


async def apply_disposition(
    *,
    correlation_id: str,
    rule_id: str,
    status: str,
    assignee: str = "",
    note: str = "",
    decided_by: str = "",
    severity: str = "",
) -> dict[str, Any]:
    """Record a triage decision: trail first, then index, then forward.

    Order matters. The trail insert is the durability guarantee, exactly as it
    is for detections themselves — if it fails, nothing is written and the
    caller gets an error rather than a UI that says "saved" over a decision
    that was never recorded. Sink forwarding is best-effort: a down SIEM must
    not lose the operator's decision.
    """
    from core.audit.ingest import _get_sink
    from core.audit.trail_db import get_trail_db

    normalized, clean_note = _validate(status, note)
    store = get_disposition_store()
    existing = store.get(correlation_id, rule_id)
    previous = existing["status"] if existing else DEFAULT_STATUS

    event = build_disposition_event(
        correlation_id=correlation_id,
        rule_id=rule_id,
        status=normalized,
        assignee=assignee,
        note=clean_note,
        decided_by=decided_by,
        previous_status=previous,
        severity=severity,
    )
    get_trail_db().insert(event)

    current = store.record(
        correlation_id=correlation_id,
        rule_id=rule_id,
        status=normalized,
        assignee=assignee,
        note=clean_note,
        decided_by=decided_by,
        decided_at_utc=event["timestamp_utc"],
        event_id=event["event_id"],
    )

    sink = _get_sink()
    if sink is not None:
        try:
            await sink.emit(event)
        except Exception:
            logger.exception("Failed to forward disposition for %s", rule_id)

    logger.info(
        "DISPOSITION %s %s -> %s by %s",
        rule_id,
        previous,
        normalized,
        decided_by or "operator",
    )
    return current


def rebuild_from_trail(trail_db: Any | None = None) -> int:
    """Replay disposition events from the trail into the store.

    The trail is the record; this table is an index over it. Used after a
    restore, and by tests that need to prove the two agree.
    """
    if trail_db is None:
        from core.audit.trail_db import get_trail_db

        trail_db = get_trail_db()

    events = trail_db.events_by_action_type(DISPOSITION_EVENT_TYPE)
    decisions = extract_dispositions(events)

    store = get_disposition_store()
    store.clear()
    replayed = 0
    for decision in decisions:
        try:
            store.record(
                correlation_id=str(decision.get("correlation_id") or ""),
                rule_id=str(decision.get("rule_id") or ""),
                status=str(decision.get("status") or DEFAULT_STATUS),
                assignee=str(decision.get("assignee") or ""),
                note=str(decision.get("note") or ""),
                decided_by=str(decision.get("decided_by") or ""),
                decided_at_utc=str(decision.get("ts") or ""),
            )
            replayed += 1
        except DispositionError as exc:
            logger.warning("skipping unreplayable disposition: %s", exc)
    return replayed
