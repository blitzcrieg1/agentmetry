"""Read tool calls out of an Antigravity conversation database.

The installed hook only matches `run_command`, so file reads, writes, search
and the other tools never reach the trail. The conversation database stores
every step. The payload is a protobuf blob. The tool name is a length-prefixed
ASCII field and the arguments are the JSON object that follows it. That framing
was read off a real database on 2026-10-16. A blob that does not match it
yields nothing.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator


def _varint(buf: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while index < len(buf) and shift <= 28:
        byte = buf[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7
    raise ValueError("truncated varint")


def iter_tool_calls(payload: bytes) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (tool name, arguments) from one step payload."""
    index = 0
    while True:
        marker = payload.find(b"\x12", index)
        if marker < 0 or marker + 2 >= len(payload):
            return
        name_len = payload[marker + 1]
        if name_len == 0 or name_len > 64 or name_len & 0x80:
            index = marker + 1
            continue
        name_at = marker + 2
        name_end = name_at + name_len
        if name_end >= len(payload) or payload[name_end] != 0x1A:
            index = marker + 1
            continue
        name = payload[name_at:name_end]
        if not name.isascii() or not all(chr(c).isalnum() or c == ord("_") for c in name):
            index = marker + 1
            continue
        try:
            json_len, json_at = _varint(payload, name_end + 1)
        except ValueError:
            index = marker + 1
            continue
        blob = payload[json_at : json_at + json_len]
        if not blob.startswith(b"{"):
            index = marker + 1
            continue
        try:
            args = json.loads(blob)
        except json.JSONDecodeError:
            index = marker + 1
            continue
        if isinstance(args, dict):
            yield name.decode("ascii"), args
        index = json_at + max(json_len, 1)


def tool_names(db_path: Path) -> dict[str, int]:
    """Count tool names in one conversation database. Arguments are not returned."""
    counts: dict[str, int] = {}
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as con:
        for (payload,) in con.execute("SELECT step_payload FROM steps"):
            if not isinstance(payload, (bytes, bytearray)):
                continue
            for name, _args in iter_tool_calls(payload):
                counts[name] = counts.get(name, 0) + 1
    return counts
