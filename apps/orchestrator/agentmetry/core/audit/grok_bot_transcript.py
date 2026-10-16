"""Grok Bot desktop chat cache to ingest payloads.

The desktop app writes the conversation to sand-client-persistence. Those
lines are the bot's own turns. They are not Cursor tool calls, and posting
them without source_app grok_bot used to land them as unknown or, before
that, as Cursor.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def message_text(entry: dict[str, Any]) -> str:
    if entry.get("kind") == "message":
        text = entry.get("content")
        return text if isinstance(text, str) else ""
    message = entry.get("message")
    if isinstance(message, dict):
        text = message.get("content")
        return text if isinstance(text, str) else ""
    return ""


def _timestamp(entry: dict[str, Any]) -> str:
    raw = entry.get("timestampMs")
    if isinstance(raw, (int, float)) and raw > 1_000_000_000_000:
        return datetime.fromtimestamp(raw / 1000, timezone.utc).isoformat()
    return ""


def payloads_for_entries(entries: list[dict[str, Any]], *, agent_id: str) -> list[dict[str, Any]]:
    """One ingest payload per chat line. The command column carries the text."""
    out: list[dict[str, Any]] = []
    for entry in entries:
        text = message_text(entry).strip()
        entry_id = str(entry.get("id") or "")
        if not text or not entry_id:
            continue
        role = "user" if entry.get("role") == "user" else "assistant"
        payload: dict[str, Any] = {
            "source_app": "grok_bot",
            "adapter": "grok_bot_transcript",
            "event_type": "tool_called",
            "correlation_id": agent_id,
            "outcome": "success",
            "tool": {
                "qualified": f"grok_bot.{role}",
                "server": "grok_bot",
                "command": text[:2000],
            },
        }
        stamp = _timestamp(entry)
        if stamp:
            payload["timestamp_utc"] = stamp
        out.append(payload)
    return out
