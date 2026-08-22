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

from agentmetry.core.audit.canonical import SCHEMA_VERSION
from agentmetry.core.audit.identity import identity_fields

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


def _loggable(value: object, *, limit: int = 120) -> str:
    """Flatten a value so it cannot forge log lines.

    `rule_id`, `decided_by` and the disposition keys derived from
    `correlation_id` all originate outside this process: a rule id can come from
    an operator's YAML, a correlation id comes from the agent. A newline in any
    of them lets the writer append whatever they like to the orchestrator log,
    including lines that look like ours.

    The bound is worth stating precisely. The trail is unaffected: canonical
    events are JSON and the encoder escapes a newline inside a string, so
    evidence was never forgeable this way. This protects the operator log, which
    is what a human reads while deciding whether the evidence is worth opening.

    The replacements are written out one call at a time on purpose. An earlier
    version did the same job with `str.encode("unicode_escape")`, which is
    shorter and which CodeQL cannot follow, so `py/log-injection` stayed open on
    code that was already fixed. A sanitizer the scanner does not recognise
    leaves you arguing with a dashboard instead of reading it.

    Line breaks become visible escapes rather than disappearing, so a value that
    contained one still looks different from one that did not.
    """
    text = str(value)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    # Backslash first, or the escapes introduced below get double-escaped.
    text = text.replace("\\", "\\\\")
    text = text.replace("\r", "\\r")
    text = text.replace("\n", "\\n")
    text = text.replace("\t", "\\t")
    # Anything else non-printable (NUL, the ESC that starts an ANSI sequence)
    # is dropped rather than escaped: it carries no meaning a reader needs and
    # a terminal will act on some of it.
    return "".join(ch for ch in text if ch.isprintable())


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

    The rule id is canonicalised through `RULE_ALIASES` first. A rule id stops
    being an implementation detail the moment someone dispositions a finding
    under it: rename it in place and every "we checked, it was our CI bot" ever
    recorded is orphaned, and the evidence pack reports those periods as
    untriaged. Renames are declared, and the key follows the rule.
    """
    from .rules import canonical_rule_id

    corr = (correlation_id or "").strip()
    rule = (rule_id or "").strip()
    if not rule:
        raise DispositionError("rule_id is required")
    return f"{corr}::{canonical_rule_id(rule)}"


def _candidate_keys(correlation_id: str, rule_id: str) -> list[str]:
    """The canonical key first, then any this detection used to be stored under."""
    from .rules import canonical_rule_id, historical_rule_ids

    corr = (correlation_id or "").strip()
    canonical = canonical_rule_id(rule_id)
    keys = [f"{corr}::{canonical}"]
    keys.extend(f"{corr}::{old}" for old in historical_rule_ids(canonical))
    return keys


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_rule_id(rule_id: str) -> str:
    """Reject a decision about a rule that does not exist.

    The cheapest place to stop an orphan is before it is written. A typo in a
    rule id produces a disposition nothing will ever match, which reads later as
    a finding somebody reviewed and a separate finding nobody did.

    Deliberately not applied on replay: the trail is the record, and an event
    naming a since-retired rule still happened. `orphaned()` surfaces those.
    """
    from .rules import canonical_rule_id, known_rule_ids

    rule = (rule_id or "").strip()
    if not rule:
        raise DispositionError("rule_id is required")
    known = known_rule_ids()
    if rule not in known and canonical_rule_id(rule) not in known:
        raise DispositionError(
            f"unknown rule_id {rule!r}. Dispositioning a rule that does not "
            "exist would create a decision nothing can ever match."
        )
    return canonical_rule_id(rule)


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
        from .rules import canonical_rule_id

        normalized, clean_note = _validate(status, note)
        key = detection_key(correlation_id, rule_id)
        decided_at = decided_at_utc or _now()
        clean_assignee = (assignee or "").strip()[:_MAX_ASSIGNEE_CHARS]

        conn = self._get_conn()
        # Look under historical keys too. A rule renamed since the last decision
        # must continue that decision's history rather than starting a second
        # row beside it, which would read as an untriaged finding plus an
        # orphan. Writing under the canonical key migrates the row in passing.
        row = self._find_row(correlation_id, rule_id)
        history: list[dict[str, Any]] = []
        first_seen = decided_at
        if row is not None:
            try:
                history = json.loads(row["history_json"]) or []
            except (json.JSONDecodeError, TypeError):
                history = []
            first_seen = row["first_seen_utc"] or decided_at
            stale_key = str(row["detection_key"])
            if stale_key != key:
                conn.execute(
                    "DELETE FROM detection_dispositions WHERE detection_key = ?",
                    (stale_key,),
                )
                logger.info(
                    "Migrated disposition %s -> %s after rule rename",
                    _loggable(stale_key),
                    _loggable(key),
                )

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
                # Store the canonical id so `orphaned()` and the dashboard agree
                # with the key. The name used at decision time survives in the
                # trail event, which is the record.
                canonical_rule_id(rule_id),
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

    def _find_row(self, correlation_id: str, rule_id: str) -> sqlite3.Row | None:
        """Look under the current key, then under any pre-rename key."""
        conn = self._get_conn()
        for key in _candidate_keys(correlation_id, rule_id):
            row = conn.execute(
                "SELECT * FROM detection_dispositions WHERE detection_key = ?",
                (key,),
            ).fetchone()
            if row is not None:
                return row
        return None

    def get(self, correlation_id: str, rule_id: str) -> dict[str, Any] | None:
        row = self._find_row(correlation_id, rule_id)
        return _row_to_dict(row) if row is not None else None

    def for_correlation(self, correlation_id: str) -> dict[str, dict[str, Any]]:
        """Current state for one session, keyed by the rule id in force today.

        Rows written before a rename are returned under the new name, so a
        caller holding today's detections finds yesterday's decisions.
        """
        from .rules import canonical_rule_id

        rows = self._get_conn().execute(
            "SELECT * FROM detection_dispositions WHERE correlation_id = ?",
            ((correlation_id or "").strip(),),
        ).fetchall()
        return {
            canonical_rule_id(str(row["rule_id"])): _row_to_dict(row) for row in rows
        }

    def orphaned(self) -> list[dict[str, Any]]:
        """Dispositions whose rule no longer exists.

        Deleting a rule does not delete the decisions made about it, and it must
        not: they are evidence of what a human concluded, and quietly dropping
        them would make a reviewed period look unreviewed. They are surfaced
        instead, so an auditor sees "decided, rule since retired" rather than a
        silent gap.
        """
        from .rules import known_rule_ids

        known = known_rule_ids()
        return [row for row in self.all() if row["rule_id"] not in known]

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
    from agentmetry.core.config import settings

    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "session_id": "",
        "timestamp_utc": _now(),
        **identity_fields(),
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
            # The trail event's own id, so a replayed row still points back at
            # the line that recorded the decision.
            "event_id": event.get("event_id"),
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
                from agentmetry.core.config import settings

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
    from agentmetry.core.audit.ingest import _get_sink
    from agentmetry.core.audit.trail_db import get_trail_db

    normalized, clean_note = _validate(status, note)
    rule_id = validate_rule_id(rule_id)
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
            logger.exception("Failed to forward disposition for %s", _loggable(rule_id))

    # `previous` and `normalized` are validated against STATUSES before they get
    # here, so passing them raw was safe and CodeQL kept flagging them anyway.
    # Sanitizing a closed-set value is a no-op, and a no-op costs less than a
    # dismissal somebody has to re-justify every time the tab is read.
    logger.info(
        "DISPOSITION %s %s -> %s by %s",
        _loggable(rule_id),
        _loggable(previous),
        _loggable(normalized),
        _loggable(decided_by or "operator"),
    )
    return current


class DispositionRebuildRefused(RuntimeError):
    """The trail cannot account for decisions the index already holds.

    Raised instead of destroying them. Carries the orphaned keys so the
    operator is told exactly what would have been lost.
    """

    def __init__(self, missing: set[str]) -> None:
        self.missing = missing
        super().__init__(
            f"{len(missing)} disposition(s) in the index have no matching event "
            "in the trail; refusing to rebuild. Restore the trail, or pass "
            "force=True to accept the loss."
        )


def _replay_decisions(decisions: list[dict[str, Any]], store: DispositionStore) -> int:
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
                event_id=str(decision.get("event_id") or ""),
            )
            replayed += 1
        except DispositionError as exc:
            logger.warning("skipping unreplayable disposition: %s", exc)
    return replayed


def rebuild_from_trail(
    trail_db: Any | None = None, *, force: bool = False
) -> int:
    """Replay disposition events from the trail into the index.

    The trail is the record and this table is an index over it, so replaying is
    normally safe. It is not unconditionally safe, and that distinction is the
    whole point of this function's shape.

    Rebuilding starts by emptying the index. If the trail has been pruned,
    rotated, restored from a partial backup, or simply repointed at a different
    path, replay produces fewer decisions than the index held and the missing
    ones are gone. Losing triage history is worse than losing detections: the
    findings survive, so the period reads as *untriaged* rather than *unknown*,
    which is exactly backwards for ISO/IEC 42001 cl. 10 evidence.

    So a rebuild that cannot account for every key already in the index raises
    `DispositionRebuildRefused` rather than proceeding. `force=True` accepts the
    loss and is for an operator who knows why.
    """
    if trail_db is None:
        from agentmetry.core.audit.trail_db import get_trail_db

        trail_db = get_trail_db()

    decisions = extract_dispositions(
        trail_db.events_by_action_type(DISPOSITION_EVENT_TYPE)
    )

    store = get_disposition_store()
    in_trail = {
        detection_key(
            str(d.get("correlation_id") or ""), str(d.get("rule_id") or "")
        )
        for d in decisions
        if d.get("rule_id")
    }
    in_index = {str(row["detection_key"]) for row in store.all()}

    missing = in_index - in_trail
    if missing and not force:
        raise DispositionRebuildRefused(missing)

    store.clear()
    return _replay_decisions(decisions, store)


def reconcile_at_boot(trail_db: Any | None = None) -> int:
    """Bring the index up to date at startup without ever destroying it.

    Returns the number of decisions replayed, or -1 when reconciliation was
    declined. Declining is a warning, never a failure: an orchestrator that
    refuses to start because its triage index disagrees with its trail is worse
    than one that starts and says so.
    """
    try:
        replayed = rebuild_from_trail(trail_db)
    except DispositionRebuildRefused as exc:
        logger.warning(
            "Triage index NOT rebuilt: %s Sample: %s",
            exc,
            ", ".join(sorted(exc.missing)[:5]),
        )
        return -1
    if replayed:
        logger.info("Replayed %d disposition(s) from the trail", replayed)
    return replayed
