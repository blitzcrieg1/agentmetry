"""Run history API — surfaces the JSONL audit log and per-thread node traces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from core.execution.context import telemetry
from core.graphs.node_events import node_events_path
from core.notifiers.audit import audit_path

router = APIRouter(prefix="/runs", tags=["runs"])

# Read at most this many trailing lines per request; the JSONL grows forever.
_MAX_TAIL_LINES = 2000


def read_jsonl_tail(path: Path, max_lines: int = _MAX_TAIL_LINES) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-max_lines:]
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def summarize_runs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse audit events to one record per run, newest first.

    A run emits several lines over its lifetime (waiting_for_input, then
    approved, ...); later events win. Lines without a thread_id (e.g.
    degraded rejections) are kept as standalone records.
    """
    runs: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    anonymous = 0

    for event in events:
        key = event.get("thread_id")
        if not key:
            anonymous += 1
            key = f"anon-{anonymous}"
        if key not in runs:
            runs[key] = {
                "thread_id": event.get("thread_id"),
                "started": event.get("ts"),
            }
            order.append(key)
        record = runs[key]
        record["updated"] = event.get("ts")
        for field in (
            "skill",
            "status",
            "triggered_by",
            "trigger_rule_id",
            "session_id",
            "cost",
            "latency_ms",
            "archive_path",
            "error",
        ):
            if event.get(field) is not None:
                record[field] = event[field]

    return [runs[key] for key in reversed(order)]


@router.get("/")
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    records = summarize_runs(read_jsonl_tail(audit_path()))
    return {
        "total": len(records),
        "runs": records[offset : offset + limit],
    }


@router.get("/stats")
async def run_stats(window_days: int = Query(7, ge=1, le=90)):
    """Per-skill usage over a trailing window + the dogfooding go/no-go answer."""
    return telemetry.get_skill_stats(window_days)


@router.get("/{thread_id}/events")
async def run_node_events(thread_id: str):
    events = read_jsonl_tail(node_events_path(), max_lines=5000)
    return {
        "thread_id": thread_id,
        "events": [e for e in events if e.get("thread_id") == thread_id],
    }
