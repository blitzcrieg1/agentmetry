"""Hourly pending-approval digest written to the vault."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from core.execution.context import obsidian, pending_threads

logger = logging.getLogger(__name__)


async def write_approval_digest() -> None:
    """Write Approvals-Digest.md listing threads awaiting human approval."""
    lines = [
        "# Pending Approvals Digest",
        "",
        f"_Updated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    if not pending_threads:
        lines.append("_No pending approvals._")
    else:
        for thread_id, meta in pending_threads.items():
            skill = meta.get("skill_name", "unknown")
            loop_path = meta.get("active_loop_path", "")
            name = Path(loop_path).name if loop_path else "active-loop"
            lines.append(f"- **{skill}** — thread `{thread_id[:8]}…` — `{name}`")

    obsidian.write_system_note("Approvals-Digest.md", "\n".join(lines) + "\n")
    logger.info("Wrote approval digest (%d pending)", len(pending_threads))
