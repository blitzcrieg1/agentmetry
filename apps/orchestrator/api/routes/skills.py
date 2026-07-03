from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.websocket import ws_manager
from core.auth import require_api_key
from core.execution.context import (
    obsidian,
    pending_store,
    pending_threads,
    skill_registry,
    telemetry,
)
from core.execution.service import (
    run_skill,
    _finalize_execution,
)
from core.graphs.registry import SkillRegistry

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillRequest(BaseModel):
    skill_name: str
    user_input: str
    session_id: str


class ApprovalRequest(BaseModel):
    thread_id: str
    approved: bool
    modified_input: str | None = None


@router.get("/")
async def list_skills():
    return {
        "skills": obsidian.list_skills(),
        "registered_graphs": skill_registry.list_registered(),
        "available_graph_types": SkillRegistry.available_graph_types(),
        "pending_approvals": list(pending_threads.keys()),
    }


@router.get("/pending")
async def list_pending():
    return {"pending": list(pending_threads.keys())}


@router.post("/reload", dependencies=[Depends(require_api_key)])
async def reload_skills():
    """Re-scan vault skill definitions and refresh graph registry."""
    skill_registry.reload()
    return {
        "registered": skill_registry.list_registered(),
        "available_graph_types": SkillRegistry.available_graph_types(),
    }


@router.post("/execute", dependencies=[Depends(require_api_key)])
async def execute_skill(request: SkillRequest):
    result = await run_skill(
        request.skill_name,
        request.user_input,
        request.session_id,
        triggered_by="manual",
    )
    if result.get("status") == "failed" and "not found" in result.get("error", "").lower():
        raise HTTPException(status_code=404, detail=result["error"])
    if result.get("status") == "failed" and "No graph registered" in result.get("error", ""):
        raise HTTPException(status_code=400, detail=result["error"])
    if result.get("degraded"):
        raise HTTPException(status_code=503, detail=result.get("error", "LLM degraded"))
    return result


@router.post("/approve", dependencies=[Depends(require_api_key)])
async def approve_skill(request: ApprovalRequest):
    pending = pending_threads.get(request.thread_id)
    if not pending:
        pending = pending_store.get(request.thread_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Thread not found or already resolved")

    if not request.approved:
        obsidian.resolve_active_loop(
            pending["active_loop_path"],
            "terminated",
            note="Terminated by user",
        )
        obsidian.write_crash_report(
            request.thread_id, "Terminated by user", pending["skill_name"]
        )
        pending_threads.pop(request.thread_id, None)
        pending_store.delete(request.thread_id)
        await ws_manager.broadcast(pending["session_id"], {
            "type": "execution_terminated",
            "thread_id": request.thread_id,
        })
        telemetry.log_execution(
            request.thread_id, pending["skill_name"], "terminated"
        )
        return {"status": "terminated", "thread_id": request.thread_id}

    graph = skill_registry.get(pending["skill_name"])
    if not graph:
        raise HTTPException(status_code=400, detail="Graph no longer registered")
    await graph.aupdate_state(
        pending["config"],
        {"approved": True, "modified_input": request.modified_input},
    )
    final_state = await graph.ainvoke(None, pending["config"])
    snapshot = await graph.aget_state(pending["config"])
    state_values = dict(snapshot.values) if snapshot.values else final_state

    result = await _finalize_execution(
        thread_id=request.thread_id,
        skill_name=pending["skill_name"],
        session_id=pending["session_id"],
        final_state=state_values,
        active_loop_path=pending["active_loop_path"],
        start=pending["start"],
        status_label="approved",
    )

    pending_threads.pop(request.thread_id, None)
    pending_store.delete(request.thread_id)
    return result
