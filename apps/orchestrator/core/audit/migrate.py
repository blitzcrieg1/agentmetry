"""Backfill the SQLite query store from the existing JSONL trail.

Runs once on startup. Every failure mode here is non-fatal by design: the JSONL
trail is the durable record and the DB is a query index, so a broken index must
never stop the recorder from booting.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.audit.trail_db import get_trail_db
from core.config import settings

logger = logging.getLogger(__name__)

_BATCH = 1000


def backfill_db_from_jsonl() -> int:
    """Insert any JSONL events missing from the DB. Returns rows inserted.

    Idempotent: insert_batch uses INSERT OR IGNORE against a UNIQUE event_id, so
    re-running costs a scan and inserts nothing new. That is why this no longer
    returns early when the DB is non-empty. The previous version did, which meant
    a crash part-way through the first backfill left the DB permanently and
    silently partial: every later start saw rows, assumed the job was done, and
    the rest of the trail was never queryable.
    """
    jsonl_path = Path(settings.audit_export_path)
    if not jsonl_path.is_file():
        return 0

    try:
        db = get_trail_db()
    except Exception:
        logger.exception("Audit DB unavailable; skipping backfill (JSONL trail unaffected)")
        return 0

    total = 0
    batch: list[dict] = []
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                batch.append(event)
                if len(batch) >= _BATCH:
                    total += db.insert_batch(batch)
                    batch.clear()
            if batch:
                total += db.insert_batch(batch)
    except Exception as exc:
        logger.warning(
            "Audit trail backfill stopped early (%s); the JSONL trail is unaffected", exc
        )
        return total

    if total:
        logger.info("Audit trail backfill inserted %d new event(s)", total)
    return total
