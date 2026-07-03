"""Event replay API — reconnecting clients catch up from the durable outbox."""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.bus.outbox import get_outbox

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/")
async def list_events(
    since: int = Query(0, ge=0, description="Return events with seq greater than this"),
    limit: int = Query(500, ge=1, le=2000),
):
    outbox = get_outbox()
    return {
        "events": outbox.read_since(since, limit),
        "latest_seq": outbox.max_seq(),
    }
