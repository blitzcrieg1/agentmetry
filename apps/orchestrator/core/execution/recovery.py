"""Crash recovery — reconcile stale active-loop notes after an unclean stop.

A hard kill (taskkill, power loss) leaves 20-Active-Loops/ notes frozen at
`status: running` or `awaiting_approval` with no live thread behind them.
This module classifies them so the operator can clear the board without
hand-editing frontmatter — and, for orphans, can resume the run from its
LangGraph checkpoint instead of discarding the work (``resume_orphan``).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.execution.context import obsidian, pending_threads
from core.memory.obsidian_client import ObsidianClient

logger = logging.getLogger(__name__)

_ACTIONS = {
    "mark_failed": ("failed", "Orphaned by crash — marked failed via recovery"),
    "dismiss": ("dismissed", "Dismissed via recovery"),
}

_ACTIVE_STATUSES = frozenset({"running", "awaiting_approval"})


def scan_recovery(
    client: ObsidianClient | None = None,
    pending: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Classify stale active loops.

    - ``orphan``: note says running, but no run survived the restart
      (mid-run graph resumption is not supported — the checkpoint exists,
      but re-entry is a future feature).
    - ``stale_approval``: note says awaiting_approval, but the pending
      thread is gone (e.g. its interrupt row was cleaned up).
    Healthy approvals (thread still pending) and terminal notes are skipped.
    """
    vault = client or obsidian
    live = pending if pending is not None else pending_threads

    items: list[dict[str, Any]] = []
    for loop in vault.list_active_loops():
        status = loop.get("status")
        if status == "running":
            items.append({**loop, "classification": "orphan"})
        elif status == "awaiting_approval" and loop.get("thread_id") not in live:
            items.append({**loop, "classification": "stale_approval"})
    return items


def _parse_iso_timestamp(value: str) -> datetime | None:
    if not value or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _loop_resolved_age_days(loop: dict[str, Any], *, now: datetime | None = None) -> float | None:
    """Days since the loop reached a terminal state; None if timestamp missing."""
    ts = _parse_iso_timestamp(loop.get("resolved", "")) or _parse_iso_timestamp(
        loop.get("created", "")
    )
    if ts is None:
        return None
    reference = now or datetime.now(timezone.utc)
    return (reference - ts).total_seconds() / 86400


def scan_archivable_loops(
    client: ObsidianClient | None = None,
    *,
    max_age_days: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Terminal active-loop notes older than max_age_days, ready to leave 20-Active-Loops/."""
    vault = client or obsidian
    age_limit = max_age_days if max_age_days is not None else settings.active_loop_archive_days
    items: list[dict[str, Any]] = []
    for loop in vault.list_active_loops():
        status = loop.get("status", "")
        if status in _ACTIVE_STATUSES:
            continue
        age_days = _loop_resolved_age_days(loop, now=now)
        if age_days is None or age_days < age_limit:
            continue
        items.append({**loop, "classification": "archivable", "age_days": round(age_days, 1)})
    return items


def archive_stale_resolved_loops(
    client: ObsidianClient | None = None,
    *,
    max_age_days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> list[str]:
    """Move terminal loops older than max_age_days to 30-Archive/active-loops/."""
    vault = client or obsidian
    archived: list[str] = []
    for loop in scan_archivable_loops(client=vault, max_age_days=max_age_days, now=now):
        rel_path = loop["path"]
        if dry_run:
            archived.append(rel_path)
            continue
        dest = vault.archive_active_loop(rel_path)
        if dest is not None:
            archived.append(rel_path)
            logger.info("Archived stale active loop %s -> %s", rel_path, dest.name)
    return archived


def archive_resolved_loops_on_startup() -> int:
    """Opt-in boot cleanup (BLACKBOX_ACTIVE_LOOP_AUTO_ARCHIVE=false to disable)."""
    if not settings.active_loop_auto_archive:
        return 0
    archived = archive_stale_resolved_loops(max_age_days=settings.active_loop_archive_days)
    if archived:
        logger.info(
            "Archived %d resolved active-loop note(s) older than %d days",
            len(archived),
            settings.active_loop_archive_days,
        )
    return len(archived)


def resolve_recovery(
    rel_path: str,
    action: str,
    client: ObsidianClient | None = None,
) -> bool:
    """Apply a recovery action to a loop note. Returns False if not found."""
    if action not in _ACTIONS:
        raise ValueError(f"Unknown recovery action '{action}'")
    vault = client or obsidian
    if vault.read_note(rel_path) is None:
        return False
    status, note = _ACTIONS[action]
    vault.resolve_active_loop(rel_path, status, note=note)
    return True


def report_recovery_on_startup() -> int:
    """Log (not resolve) stale loops at boot so the operator sees them."""
    items = scan_recovery()
    if items:
        logger.warning(
            "Crash recovery: %d stale active-loop note(s) — resolve via "
            "'blackbox recovery', the dashboard Recovery panel, or "
            "GET /api/v1/skills/recovery",
            len(items),
        )
    return len(items)


def _reregister_pending(
    loop: dict[str, Any],
    config: dict[str, Any],
    state_values: dict[str, Any],
    live: dict[str, Any],
    pstore: Any,
) -> None:
    """Put a checkpoint paused at human_approval back into the pending queue."""
    thread_id = loop["thread_id"]
    meta = {
        "config": config,
        "session_id": f"recovery-{thread_id[:8]}",
        "skill_name": loop["skill"],
        "active_loop_path": loop["path"],
        "start": time.time(),
    }
    live[thread_id] = meta
    pstore.save(
        thread_id,
        skill_name=loop["skill"],
        session_id=meta["session_id"],
        active_loop_path=loop["path"],
        config=config,
        start=meta["start"],
        payload={
            "draft": state_values.get("draft", ""),
            "confidence": state_values.get("confidence_score", 0.0),
        },
    )


async def resume_orphan(
    rel_path: str,
    *,
    client: ObsidianClient | None = None,
    registry: Any | None = None,
    pending: dict[str, Any] | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Resume one orphaned run from its LangGraph checkpoint.

    The graph is re-entered with ``ainvoke(None, config)`` — the same pattern
    the approval path uses. Passing the original state instead would make
    LangGraph treat it as fresh input and restart from the entry node
    (double LLM spend, duplicate tool calls).

    Returns a dict whose ``status`` is one of:
    ``resumed_completed`` · ``resumed_waiting`` (back at the approval gate) ·
    ``unresumable`` (marked failed where sensible) · ``deferred`` · ``failed``.
    """
    from core.execution.context import pending_store, skill_registry
    from core.kernel.scheduler import Priority, get_scheduler, run_priority
    from core.llm.degraded import llm_degraded

    vault = client or obsidian
    reg = registry if registry is not None else skill_registry
    live = pending if pending is not None else pending_threads
    pstore = store if store is not None else pending_store

    loop = next(
        (item for item in scan_recovery(client=vault, pending=live) if item["path"] == rel_path),
        None,
    )
    if loop is None or loop["classification"] != "orphan":
        return {"status": "unresumable", "reason": "not a resumable orphan"}

    thread_id = loop["thread_id"]
    graph = reg.get(loop["skill"])
    if graph is None:
        resolve_recovery(rel_path, "mark_failed", client=vault)
        return {"status": "unresumable", "reason": "skill no longer registered"}

    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await graph.aget_state(config)
    except Exception as exc:
        resolve_recovery(rel_path, "mark_failed", client=vault)
        return {"status": "unresumable", "reason": f"checkpoint unreadable: {exc}"}

    if not snapshot.values:
        resolve_recovery(rel_path, "mark_failed", client=vault)
        return {"status": "unresumable", "reason": "no checkpoint for this thread"}

    if snapshot.next and "human_approval" in snapshot.next:
        # Crashed exactly at the gate — re-register, don't re-run anything.
        _reregister_pending(loop, config, dict(snapshot.values), live, pstore)
        vault.resolve_active_loop(
            rel_path, "awaiting_approval", note="Recovered approval gate after crash"
        )
        logger.info("Resumed %s to approval gate (thread %s)", loop["skill"], thread_id)
        return {"status": "resumed_waiting", "thread_id": thread_id}

    from core.execution.service import _finalize_execution

    if not snapshot.next:
        # Graph actually finished; only the closeout bookkeeping was lost.
        result = await _finalize_execution(
            thread_id=thread_id,
            skill_name=loop["skill"],
            session_id=f"recovery-{thread_id[:8]}",
            final_state=dict(snapshot.values),
            active_loop_path=rel_path,
            start=time.time(),
            status_label="completed",
            triggered_by="recovery",
        )
        return {**result, "status": "resumed_completed"}

    if llm_degraded.active:
        return {"status": "deferred", "reason": "LLM degraded — retry when it clears"}

    run_priority.set(Priority.AUTONOMOUS)
    async with get_scheduler().run_slot():
        try:
            final_state = await graph.ainvoke(None, config)
        except Exception as exc:
            vault.resolve_active_loop(rel_path, "failed", note=f"Resume failed: {exc}")
            logger.warning("Resume of %s failed: %s", thread_id, exc)
            return {"status": "failed", "thread_id": thread_id, "error": str(exc)}

        snapshot = await graph.aget_state(config)
        state_values = dict(snapshot.values) if snapshot.values else dict(final_state or {})

        if snapshot.next and "human_approval" in snapshot.next:
            _reregister_pending(loop, config, state_values, live, pstore)
            vault.resolve_active_loop(
                rel_path, "awaiting_approval", note="Resumed to approval gate"
            )
            return {"status": "resumed_waiting", "thread_id": thread_id}

        result = await _finalize_execution(
            thread_id=thread_id,
            skill_name=loop["skill"],
            session_id=f"recovery-{thread_id[:8]}",
            final_state=state_values,
            active_loop_path=rel_path,
            start=time.time(),
            status_label="completed",
            triggered_by="recovery",
        )
        logger.info("Resumed %s to completion (thread %s)", loop["skill"], thread_id)
        return {**result, "status": "resumed_completed"}


async def resume_orphans_on_startup(limit: int = 3) -> int:
    """Opt-in boot auto-resume (BLACKBOX_AUTO_RESUME=1), capped per boot."""
    resumed = 0
    for loop in scan_recovery():
        if loop["classification"] != "orphan":
            continue
        if resumed >= limit:
            logger.info(
                "Auto-resume cap (%d) reached — remaining orphans left for manual review",
                limit,
            )
            break
        result = await resume_orphan(loop["path"])
        if result.get("status") in ("resumed_completed", "resumed_waiting"):
            resumed += 1
    return resumed
