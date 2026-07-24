"""Drain the hook spool at orchestrator boot.

The hook client posts events to the ingest API and must never block or crash the
IDE, so a failed POST used to print to stderr and drop the event. That punched
holes in the trail on every orchestrator restart, update, and IDE-launch race —
in a product whose entire claim is a complete record of what the agent did.

The hook now appends unreachable payloads to `data/hook-spool.jsonl`; this
module replays them through the normal ingest path on startup, so spooled events
get the same canonical build, detection correlation, and sink forwarding as live
ones. Replay is ordered by spool time, which is the order the hooks fired.

Non-fatal by design, like the JSONL backfill next door: a broken spool must never
stop the recorder from booting.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# Matches scripts/agentmetry_ingest.py — a payload older than this is dropped
# rather than replayed, because injecting a week-old tool call into today's
# correlation window produces false sequences, which is worse than a gap.
MAX_AGE_SECONDS = 7 * 24 * 3600


def spool_path() -> Path:
    return Path(settings.audit_export_path).parent / "hook-spool.jsonl"


def _too_old(spooled_at: str, *, now: datetime) -> bool:
    if not spooled_at:
        return False
    try:
        ts = datetime.fromisoformat(spooled_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts < now - timedelta(seconds=MAX_AGE_SECONDS)


def read_spool(path: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    """Return (replayable payloads, dropped count) from the spool file."""
    target = path or spool_path()
    if not target.is_file():
        return [], 0

    now = datetime.now(timezone.utc)
    payloads: list[dict[str, Any]] = []
    dropped = 0
    try:
        with target.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    dropped += 1
                    continue
                if not isinstance(row, dict):
                    dropped += 1
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    dropped += 1
                    continue
                if _too_old(str(row.get("spooled_at") or ""), now=now):
                    dropped += 1
                    continue
                payloads.append(payload)
    except OSError:
        logger.exception("Could not read hook spool at %s", target)
        return [], dropped
    return payloads, dropped


async def drain_spool(path: Path | None = None) -> dict[str, int]:
    """Replay spooled hook payloads through the ingest path. Returns counts.

    The spool file is only removed once every payload has been replayed. A crash
    mid-drain therefore replays from the start next boot; ingest is idempotent on
    `event_id`... except that spooled payloads have no `event_id` yet (it is
    minted in `build_external_canonical`), so a partial drain can duplicate.
    Duplicated events are visible and harmless; a lost event is neither. That
    trade is deliberate.
    """
    from core.audit.ingest import ingest_external_event

    target = path or spool_path()
    payloads, dropped = read_spool(target)
    if not payloads:
        if target.is_file():
            _remove(target)
        return {"replayed": 0, "failed": 0, "dropped": dropped}

    replayed = 0
    failed = 0
    for payload in payloads:
        try:
            await ingest_external_event(payload)
            replayed += 1
        except Exception:
            failed += 1

    if failed == 0:
        _remove(target)
    else:
        logger.warning(
            "Hook spool: %d payload(s) failed to replay; keeping %s for the next boot",
            failed,
            target,
        )

    logger.info(
        "Hook spool drained: %d replayed, %d failed, %d dropped (stale/corrupt)",
        replayed,
        failed,
        dropped,
    )
    return {"replayed": replayed, "failed": failed, "dropped": dropped}


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        logger.exception("Could not remove drained hook spool at %s", path)
