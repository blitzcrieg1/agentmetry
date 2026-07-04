"""Crash recovery — reconcile stale active-loop notes after an unclean stop.

A hard kill (taskkill, power loss) leaves 20-Active-Loops/ notes frozen at
`status: running` or `awaiting_approval` with no live thread behind them.
This module classifies them so the operator can clear the board without
hand-editing frontmatter.
"""

from __future__ import annotations

import logging
from typing import Any

from core.execution.context import obsidian, pending_threads
from core.memory.obsidian_client import ObsidianClient

logger = logging.getLogger(__name__)

_ACTIONS = {
    "mark_failed": ("failed", "Orphaned by crash — marked failed via recovery"),
    "dismiss": ("dismissed", "Dismissed via recovery"),
}


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
