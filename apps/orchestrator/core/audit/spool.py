"""Drain the hook spool.

The hook client posts events to the ingest API and must never block or crash the
IDE, so a failed POST used to print to stderr and drop the event. That punched
holes in the trail on every orchestrator restart, update, and IDE-launch race —
in a product whose entire claim is a complete record of what the agent did.

The hook now appends unreachable payloads to `data/hook-spool.jsonl`; this
module replays them through the normal ingest path so spooled events get the
same canonical build, detection correlation, and sink forwarding as live ones.
Replay is ordered by spool time, which is the order the hooks fired.

Non-fatal by design, like the JSONL backfill next door: a broken spool must never
stop the recorder from booting.

Three properties this module has to hold, each of which it failed to hold once:

**Draining must not delete what it never read.** The first version read the whole
file, replayed it, then unlinked the path. A drain of a few thousand events takes
minutes, and the hooks keep appending the whole time, so the unlink destroyed
every event captured during the drain — silently, and worst on exactly the busy
machines the spool exists to protect. The file is now rotated aside first: hooks
immediately start a fresh spool, and only the rotated copy is ever deleted.

**Draining must not be the reason the recorder is unreachable.** Awaiting the
drain inside the FastAPI lifespan kept the ingest port closed until it finished,
so every hook firing during a large drain was refused and spooled, which made the
next drain larger. The boot drain now runs as a background task.

**An expired payload must leave a scar.** Payloads past `MAX_AGE_SECONDS` are not
replayed, because injecting a week-old tool call into today's correlation window
produces false sequences, which is worse than a gap. They are moved to
`hook-spool.expired.jsonl` rather than deleted. A gap in an audit trail is a fact
about the audit trail, and this product does not get to quietly forget one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# Matches scripts/agentmetry_ingest.py — a payload older than this is not
# replayed. It is quarantined, never discarded.
MAX_AGE_SECONDS = 7 * 24 * 3600

# How often the background drain looks for work once the recorder is up.
DRAIN_INTERVAL_SECONDS = 60

# Windows will refuse the rename while a hook process has the file open for
# append. That window is one short write, so a few retries clear it.
_ROTATE_ATTEMPTS = 5
_ROTATE_BACKOFF_SECONDS = 0.2

# One drain at a time. The boot drain and the periodic drain would otherwise
# rotate and replay the same file concurrently and double every event in it.
_drain_lock = asyncio.Lock()


def spool_path() -> Path:
    return Path(settings.audit_export_path).parent / "hook-spool.jsonl"


def expired_path(path: Path | None = None) -> Path:
    target = path or spool_path()
    return target.with_name("hook-spool.expired.jsonl")


def _draining_glob(path: Path) -> str:
    return path.name + ".draining.*"


def _pending_files(path: Path) -> list[Path]:
    """Rotated files a previous drain did not finish, oldest first.

    Names embed a monotonic-enough timestamp, so lexical order is chronological
    order, which is the order the hooks fired.
    """
    try:
        return sorted(path.parent.glob(_draining_glob(path)))
    except OSError:
        return []


# ----------------------------------------------------------------------
# Inspection — read-only, safe to call from doctor/dogfood/API handlers
# ----------------------------------------------------------------------


def _count_lines(target: Path) -> int:
    if not target.is_file():
        return 0
    total = 0
    try:
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                total += chunk.count(b"\n")
    except OSError:
        return 0
    return total


def spool_depth(path: Path | None = None) -> int:
    """Events waiting to be replayed, including any mid-drain rotated files.

    Counts newlines rather than parsing, so this stays cheap enough to call on
    every status poll.
    """
    target = path or spool_path()
    return _count_lines(target) + sum(_count_lines(p) for p in _pending_files(target))


def _first_spooled_at(target: Path) -> datetime | None:
    if not target.is_file():
        return None
    try:
        with target.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_ts(str((row or {}).get("spooled_at") or ""))
                if ts is not None:
                    return ts
    except OSError:
        return None
    return None


def spool_oldest_age_seconds(path: Path | None = None) -> float | None:
    """Age of the oldest pending payload, or None when nothing is pending.

    This is the number that matters operationally: depth tells you how much is
    waiting, age tells you how close it is to being unreplayable.
    """
    target = path or spool_path()
    candidates = [*_pending_files(target), target]
    oldest: datetime | None = None
    for candidate in candidates:
        ts = _first_spooled_at(candidate)
        if ts is not None and (oldest is None or ts < oldest):
            oldest = ts
    if oldest is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - oldest).total_seconds())


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _too_old(spooled_at: str, *, now: datetime) -> bool:
    ts = _parse_ts(spooled_at)
    if ts is None:
        # An unparseable or absent timestamp is not evidence of age. Replay it;
        # a duplicate is recoverable and a silent drop is not.
        return False
    return ts < now - timedelta(seconds=MAX_AGE_SECONDS)


def read_spool(path: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    """Return (replayable payloads, unreplayable count) without touching the file.

    Pure inspection: `doctor` and the dogfood report call this to size the
    backlog, and neither should have a side effect on the trail.
    """
    target = path or spool_path()
    payloads, expired, corrupt = _parse_file(target)
    return payloads, len(expired) + corrupt


def _parse_file(target: Path) -> tuple[list[dict[str, Any]], list[str], int]:
    """(replayable payloads, raw expired lines, corrupt line count)."""
    if not target.is_file():
        return [], [], 0

    now = datetime.now(timezone.utc)
    payloads: list[dict[str, Any]] = []
    expired: list[str] = []
    corrupt = 0
    try:
        with target.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError:
                    corrupt += 1
                    continue
                if not isinstance(row, dict):
                    corrupt += 1
                    continue
                payload = row.get("payload")
                if not isinstance(payload, dict):
                    corrupt += 1
                    continue
                if _too_old(str(row.get("spooled_at") or ""), now=now):
                    expired.append(stripped)
                    continue
                payloads.append(payload)
    except OSError:
        logger.exception("Could not read hook spool at %s", target)
        return [], [], corrupt
    return payloads, expired, corrupt


# ----------------------------------------------------------------------
# Draining — mutates the spool, one caller at a time
# ----------------------------------------------------------------------


def _rotate(path: Path) -> Path | None:
    """Move the live spool aside so hooks keep appending to a fresh file.

    Returns the rotated path, or None when there was nothing to rotate or the
    rename could not be taken. Failing to rotate is safe: nothing has been read
    and nothing has been deleted, so the next drain tries again.
    """
    if not path.is_file() or path.stat().st_size == 0:
        return None

    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    for attempt in range(_ROTATE_ATTEMPTS):
        target = path.with_name(f"{path.name}.draining.{stamp}.{attempt}")
        try:
            os.replace(path, target)
            return target
        except OSError:
            time.sleep(_ROTATE_BACKOFF_SECONDS)
    logger.warning(
        "Could not rotate hook spool at %s; leaving it for the next drain", path
    )
    return None


def _quarantine(lines: list[str], *, path: Path) -> int:
    """Append expired raw lines to the quarantine file. Never deletes."""
    if not lines:
        return 0
    target = expired_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
    except OSError:
        logger.exception(
            "Could not quarantine %d expired spool payload(s) to %s; keeping them "
            "in place rather than dropping them",
            len(lines),
            target,
        )
        return 0
    return len(lines)


async def _drain_one(target: Path) -> dict[str, int]:
    from core.audit.ingest import ingest_external_event

    payloads, expired, corrupt = _parse_file(target)
    quarantined = _quarantine(expired, path=target)

    replayed = 0
    failed = 0
    for payload in payloads:
        try:
            await ingest_external_event(payload)
            replayed += 1
        except Exception:
            failed += 1

    # Only let go of the rotated file once every payload in it is accounted for.
    # Expired payloads count as accounted for exactly when they reached
    # quarantine; if that write failed, keep the file.
    if failed == 0 and quarantined == len(expired):
        _remove(target)
    else:
        logger.warning(
            "Hook spool: %d payload(s) failed to replay and %d expired payload(s) "
            "could not be quarantined; keeping %s",
            failed,
            len(expired) - quarantined,
            target,
        )

    return {
        "replayed": replayed,
        "failed": failed,
        "expired": quarantined,
        "corrupt": corrupt,
    }


async def drain_spool(path: Path | None = None) -> dict[str, int]:
    """Replay spooled hook payloads through the ingest path. Returns counts.

    Picks up rotated files a previous drain left behind before rotating the live
    spool, so a crash mid-drain resumes rather than restarts.

    Replay is idempotent on `event_id`, except that spooled payloads have no
    `event_id` yet (it is minted in `build_external_canonical`), so an
    interrupted drain can duplicate. Duplicated events are visible and harmless;
    a lost event is neither. That trade is deliberate.
    """
    target = path or spool_path()

    if _drain_lock.locked():
        logger.debug("Hook spool drain already in progress; skipping this pass")
        return {"replayed": 0, "failed": 0, "expired": 0, "corrupt": 0, "skipped": 1}

    async with _drain_lock:
        pending = _pending_files(target)
        rotated = _rotate(target)
        if rotated is not None:
            pending.append(rotated)

        totals = {"replayed": 0, "failed": 0, "expired": 0, "corrupt": 0}
        for candidate in pending:
            result = await _drain_one(candidate)
            for key in totals:
                totals[key] += result[key]

        if any(totals.values()):
            logger.info(
                "Hook spool drained: %d replayed, %d failed, %d expired, %d corrupt",
                totals["replayed"],
                totals["failed"],
                totals["expired"],
                totals["corrupt"],
            )
        return totals


async def drain_forever(interval: float = DRAIN_INTERVAL_SECONDS) -> None:
    """Background task: keep the spool drained for as long as the recorder runs.

    A boot-only drain means an orchestrator that stays up while the network path
    to it breaks accumulates a backlog until someone happens to restart it. The
    recorder should heal without a human noticing there was anything to heal.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            result = await drain_spool()
            if result.get("replayed"):
                logger.info(
                    "Hook spool: replayed %d event(s) captured while ingest was "
                    "unreachable",
                    result["replayed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic hook spool drain failed; will retry")


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        logger.exception("Could not remove drained hook spool at %s", path)
