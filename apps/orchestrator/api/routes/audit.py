"""AgentAudit read-only API — tail of forwarded canonical JSONL."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from core.config import settings

router = APIRouter(prefix="/audit", tags=["audit"])


def _tail_jsonl(path: Path, limit: int) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    tail = lines[-limit:]
    events: list[dict] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


@router.get("/tail")
async def audit_tail(limit: int = Query(50, ge=1, le=500)):
    """Return the last N canonical audit events from the local JSONL forwarder."""
    path = Path(settings.audit_export_path)
    if not settings.audit_export_enabled:
        return {"events": [], "path": str(path), "enabled": False}
    try:
        events = _tail_jsonl(path, limit)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"events": events, "path": str(path), "enabled": True}
