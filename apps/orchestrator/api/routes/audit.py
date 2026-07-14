"""Agentmetry API — JSONL tail + external Tier B ingest."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.auth import require_api_key
from core.audit.ingest import ingest_external_event
from core.config import settings

router = APIRouter(prefix="/audit", tags=["audit"])

_RUN_ACTION_TYPES = frozenset({
    "session_start",
    "session_end",
    "tool_called",
    "approval_request",
    "approval_response",
    "detection",  # correlated findings — must not be filtered out of the feed
})


class IngestToolBody(BaseModel):
    qualified: str = ""
    server: str = ""
    arguments: dict[str, Any] | None = None
    input_hash: str = ""
    command: str = ""


class ExternalIngestBody(BaseModel):
    """Adapter payload — normalized to canonical v1.1 on ingest."""

    source_app: str = Field(..., description="cursor | claude | antigravity | codex | mcp_proxy")
    event_type: str = Field(
        ...,
        description="session_start | session_end | tool_called | tool_denied | tool_failed | approval_request | approval_response",
    )
    correlation_id: str = ""
    session_id: str = ""
    outcome: str = ""
    reason: str = ""
    skill_id: str = ""
    tool_qualified: str = ""
    tool: IngestToolBody | None = None
    input_hash: str = ""
    model_id: str = ""
    adapter: str = ""
    triggered_by: str = "manual"
    timestamp_utc: str = ""
    gated_action: dict[str, str] | None = None
    # DLP verdict from the hook process. It scans plaintext before hashing, so
    # this is the only place the finding can be captured — without this field
    # pydantic drops it and a `log`-mode match is silently lost.
    dlp: dict[str, Any] | None = None


def _tail_jsonl(path: Path, *, read_lines: int) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    tail = lines[-read_lines:]
    return _parse_jsonl_lines(tail)


def _read_jsonl(path: Path, *, max_lines: int = 50_000) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return _parse_jsonl_lines(lines)


def _parse_jsonl_lines(lines: list[str]) -> list[dict]:
    events: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _parse_event_ts(event: dict[str, Any]) -> datetime | None:
    ts = event.get("timestamp_utc")
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _parse_query_ts(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {value}") from exc


# Events written before the Agentmetry rename carry the legacy first-party name.
# Normalize on read so an existing trail keeps rendering instead of silently
# vanishing behind the source filter.
_LEGACY_SOURCE_APPS = frozenset({"blackbox"})


def _normalize_source_app(name: str) -> str:
    return "agentmetry" if name in _LEGACY_SOURCE_APPS else name


def _event_source_app(event: dict[str, Any]) -> str:
    source = event.get("source")
    if isinstance(source, dict) and source.get("app"):
        return _normalize_source_app(str(source["app"]).lower())
    agent = event.get("agent")
    if isinstance(agent, dict) and agent.get("name"):
        name = _normalize_source_app(str(agent["name"]).lower())
        if name != "agentmetry":
            return name
    return "agentmetry"


def _filter_events(
    events: list[dict],
    *,
    scope: Literal["runs", "all"],
    session_id: str | None,
    sources: set[str] | None,
    since_minutes: int | None,
) -> list[dict]:
    if scope == "runs":
        events = [
            e
            for e in events
            if (e.get("action") or {}).get("type") in _RUN_ACTION_TYPES
        ]
    if sources:
        events = [e for e in events if _event_source_app(e) in sources]
    if session_id:
        events = [
            e
            for e in events
            if e.get("session_id") == session_id
            or _event_source_app(e) != "agentmetry"
        ]
    if since_minutes is not None and since_minutes > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        def _after_cutoff(event: dict) -> bool:
            dt = _parse_event_ts(event)
            if dt is None:
                return True
            return dt >= cutoff

        events = [e for e in events if _after_cutoff(e)]
    return events


def _sort_events(events: list[dict]) -> list[dict]:
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def _key(event: dict) -> tuple[datetime, str]:
        ts = _parse_event_ts(event) or epoch
        eid = str(event.get("event_id") or "")
        return (ts, eid)

    return sorted(events, key=_key)


def _paginate_events(
    events: list[dict],
    *,
    limit: int,
    before_utc: str | None,
    after_utc: str | None,
) -> tuple[list[dict], dict[str, Any]]:
    sorted_events = _sort_events(events)
    if before_utc and after_utc:
        raise HTTPException(status_code=400, detail="Use only one of before_utc or after_utc")

    if before_utc:
        cutoff = _parse_query_ts(before_utc)
        pool = [e for e in sorted_events if (ts := _parse_event_ts(e)) and ts < cutoff]
        page = pool[-limit:]
        has_older = len(pool) > limit
        has_newer = True
    elif after_utc:
        cutoff = _parse_query_ts(after_utc)
        pool = [e for e in sorted_events if (ts := _parse_event_ts(e)) and ts > cutoff]
        page = pool[:limit]
        has_older = True
        has_newer = len(pool) > limit
    else:
        page = sorted_events[-limit:]
        has_older = len(sorted_events) > limit
        has_newer = False

    pagination = {
        "has_older": has_older,
        "has_newer": has_newer,
        "oldest_utc": page[0].get("timestamp_utc") if page else None,
        "newest_utc": page[-1].get("timestamp_utc") if page else None,
        "count": len(page),
    }
    return page, pagination


@router.post("/ingest", dependencies=[Depends(require_api_key)])
async def audit_ingest(body: ExternalIngestBody):
    """Accept canonical adapter events from Cursor, Claude, MCP proxy, etc."""
    if not settings.audit_ingest_enabled:
        raise HTTPException(status_code=503, detail="External audit ingest is disabled")
    if not settings.audit_export_enabled:
        raise HTTPException(status_code=503, detail="Audit export is disabled")

    payload = body.model_dump(exclude_none=True)
    try:
        canonical = await ingest_external_event(payload)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "accepted",
        "event_id": canonical.get("event_id"),
        "correlation_id": canonical.get("correlation_id"),
        "action": canonical.get("action"),
        "source": canonical.get("source"),
    }


@router.get("/tail", dependencies=[Depends(require_api_key)])
async def audit_tail(
    limit: int = Query(50, ge=1, le=500),
    scope: Literal["runs", "all"] = Query(
        "runs",
        description="runs = session/tool/approval only; all = include driver config_change",
    ),
    session_id: str | None = Query(
        None,
        description="When set, Agentmetry events filter to session; external apps always shown",
    ),
    sources: str | None = Query(
        None,
        description="Comma-separated source apps: agentmetry,cursor,claude,antigravity,mcp_proxy",
    ),
    since_minutes: int | None = Query(
        None,
        ge=1,
        le=10080,
        description="Only events within the last N minutes",
    ),
    before_utc: str | None = Query(
        None,
        description="Return events strictly before this ISO timestamp (page older)",
    ),
    after_utc: str | None = Query(
        None,
        description="Return events strictly after this ISO timestamp (page newer)",
    ),
):
    """Return canonical audit events from the local JSONL forwarder."""
    path = Path(settings.audit_export_path)
    if not settings.audit_export_enabled:
        return {"events": [], "path": str(path), "enabled": False, "pagination": {"has_older": False, "has_newer": False, "count": 0}}

    source_set: set[str] | None = None
    if sources:
        source_set = {s.strip().lower() for s in sources.split(",") if s.strip()}

    try:
        if before_utc or after_utc:
            raw = _read_jsonl(path)
        else:
            read_lines = max(limit * 20, 400)
            raw = _tail_jsonl(path, read_lines=read_lines)
        filtered = _filter_events(
            raw,
            scope=scope,
            session_id=session_id,
            sources=source_set,
            since_minutes=since_minutes,
        )
        page, pagination = _paginate_events(
            filtered, limit=limit, before_utc=before_utc, after_utc=after_utc
        )
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"events": page, "path": str(path), "enabled": True, "pagination": pagination}


@router.get("/session/{correlation_id}", dependencies=[Depends(require_api_key)])
async def audit_session(
    correlation_id: str,
    limit: int = Query(2000, ge=1, le=10000),
):
    """Return every event for one correlation_id across the whole trail.

    The dashboard's in-panel search only sees the loaded window, so viewing a
    full session — especially an older one — needs a server-side lookup that
    scans the entire JSONL rather than the last N lines.
    """
    path = Path(settings.audit_export_path)
    if not settings.audit_export_enabled:
        return {"events": [], "correlation_id": correlation_id, "enabled": False, "count": 0}
    try:
        raw = _read_jsonl(path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    matched = _sort_events([e for e in raw if e.get("correlation_id") == correlation_id])
    return {
        "events": matched[:limit],
        "correlation_id": correlation_id,
        "enabled": True,
        "count": len(matched),
    }


@router.get("/detections/{correlation_id}", dependencies=[Depends(require_api_key)])
async def audit_detections(correlation_id: str):
    """Run correlated behavioral rules over one session and return detections.

    A detection is a named, ordered pattern of events (e.g. credential access
    then network egress) — the signal per-event MITRE tags can't express on
    their own. Scans the whole trail for the session, then correlates.
    """
    from core.audit.detection import run_detections

    path = Path(settings.audit_export_path)
    if not settings.audit_export_enabled:
        return {"detections": [], "correlation_id": correlation_id, "enabled": False, "count": 0}
    try:
        raw = _read_jsonl(path)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    events = [e for e in raw if e.get("correlation_id") == correlation_id]
    detections = run_detections(events)
    return {
        "detections": [d.as_dict() for d in detections],
        "correlation_id": correlation_id,
        "enabled": True,
        "count": len(detections),
    }


@router.get("/export/evidence", dependencies=[Depends(require_api_key)])
async def audit_export_evidence():
    """Generate and download a cryptographic evidence pack."""
    from core.audit.evidence_pack import build_evidence_pack, default_export_path, write_evidence_pack
    from datetime import datetime, timedelta, timezone

    to_date = datetime.now(timezone.utc)
    from_date = to_date - timedelta(days=30)  # Export last 30 days
    
    pack = build_evidence_pack(from_date, to_date)
    out_path = default_export_path(from_date, to_date)
    write_evidence_pack(pack, out_path)
    
    return FileResponse(
        path=out_path,
        media_type="application/zip",
        filename=out_path.name,
    )


@router.get("/status", dependencies=[Depends(require_api_key)])
async def audit_status():
    """Freshness + per-source counts so the dashboard can show 'last event N min ago'.

    Powers the freshness badge and `selftest` — makes silent hook failure visible
    instead of the operator falsely believing they are being audited.
    """
    path = Path(settings.audit_export_path)
    if not settings.audit_export_enabled:
        return {"enabled": False, "last_event_utc": None, "recent": 0, "by_source": {}, "path": str(path)}

    raw = _tail_jsonl(path, read_lines=500)
    by_source: dict[str, int] = {}
    last_ts: str | None = None
    for event in raw:
        app = _event_source_app(event)
        by_source[app] = by_source.get(app, 0) + 1
        ts = event.get("timestamp_utc")
        if isinstance(ts, str) and (last_ts is None or ts > last_ts):
            last_ts = ts
    return {
        "enabled": True,
        "last_event_utc": last_ts,
        "recent": len(raw),
        "by_source": by_source,
        "path": str(path),
    }
