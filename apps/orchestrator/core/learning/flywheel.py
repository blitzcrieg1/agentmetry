"""Implicit diff flywheel — capture operator corrections without forms."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.bus.bus import bus
from core.bus.events import FLYWHEEL_CAPTURE
from core.config import settings
from core.memory.obsidian_client import ObsidianClient

logger = logging.getLogger(__name__)

EDIT_LOG_REL = ".system/feedback/edit-log.jsonl"
FLYWHEEL_MESSAGE = "Correction captured. My brain is getting smarter."


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def drafts_differ(original: str, modified: str) -> bool:
    """True when operator text meaningfully changed the AI draft."""
    return _normalize(original) != _normalize(modified)


def build_edit_entry(
    *,
    thread_id: str,
    skill_name: str,
    original_draft: str,
    modified_input: str,
) -> dict[str, Any]:
    """Structured row for future SOP-drift LLM ingestion."""
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "thread_id": thread_id,
        "skill_name": skill_name,
        "original_draft": original_draft,
        "modified_input": modified_input,
        "char_delta": len(modified_input) - len(original_draft),
    }


def append_edit_log(
    entry: dict[str, Any],
    *,
    client: ObsidianClient | None = None,
) -> None:
    """Append one JSONL record — sync, fast, append-only."""
    vault = client or ObsidianClient(settings.vault_path)
    vault.append_jsonl(EDIT_LOG_REL, entry)


async def schedule_edit_capture(
    *,
    thread_id: str,
    skill_name: str,
    session_id: str,
    original_draft: str,
    modified_input: str | None,
    client: ObsidianClient | None = None,
) -> None:
    """Fire-and-forget correction capture; never blocks approval."""
    if modified_input is None or not drafts_differ(original_draft, modified_input):
        return

    asyncio.create_task(
        _capture_edit_flywheel(
            thread_id=thread_id,
            skill_name=skill_name,
            session_id=session_id,
            original_draft=original_draft,
            modified_input=modified_input,
            client=client,
        )
    )


async def _capture_edit_flywheel(
    *,
    thread_id: str,
    skill_name: str,
    session_id: str,
    original_draft: str,
    modified_input: str,
    client: ObsidianClient | None = None,
) -> None:
    entry = build_edit_entry(
        thread_id=thread_id,
        skill_name=skill_name,
        original_draft=original_draft,
        modified_input=modified_input,
    )
    try:
        await asyncio.to_thread(append_edit_log, entry, client=client)
    except Exception:
        logger.exception("Flywheel edit-log write failed for thread %s", thread_id)
        return

    bus.publish(
        FLYWHEEL_CAPTURE,
        {
            "type": "flywheel_capture",
            "message": FLYWHEEL_MESSAGE,
            "thread_id": thread_id,
            "skill_name": skill_name,
        },
        session_id=session_id,
        thread_id=thread_id,
    )
