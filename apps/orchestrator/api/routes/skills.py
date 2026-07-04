from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.bus.bus import bus
from core.bus.events import RUN_TERMINATED
from core.auth import require_api_key
from core.execution.context import (
    interrupt_table,
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


class BatchApprovalRequest(BaseModel):
    thread_ids: list[str]
    approved: bool


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
    items = []
    for thread_id, meta in pending_threads.items():
        row = interrupt_table.get(thread_id)
        payload = (row or {}).get("payload") or {}
        items.append({
            "thread_id": thread_id,
            "skill_name": meta["skill_name"],
            "session_id": meta["session_id"],
            "vector": "hitl_approval",
            "created_at": row.get("created_at") if row else None,
            "draft": payload.get("draft", ""),
            "confidence": payload.get("confidence", 0.0),
        })
    return {"pending": items}


@router.get("/interrupts")
async def list_interrupts():
    return {"interrupts": interrupt_table.list_pending()}


@router.post("/interrupts/{interrupt_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_exec_interrupt(interrupt_id: str):
    """Approve a TOOL_EXEC_APPROVAL interrupt: run the recorded command in Tier 1."""
    from core.bus.events import INTERRUPT_RESOLVED, TOOL_CALLED
    from core.kernel.interrupts import InterruptVector
    from core.sandbox.tier1 import SandboxDenied, run_tier1

    row = interrupt_table.get(interrupt_id)
    if not row or row.get("vector") != InterruptVector.TOOL_EXEC_APPROVAL:
        raise HTTPException(status_code=404, detail="No such exec interrupt")

    skill_config = obsidian.read_skill_config(row["skill_name"]) or {}
    if skill_config.get("sandbox_tier") != 1:
        raise HTTPException(
            status_code=400,
            detail=f"Skill '{row['skill_name']}' does not declare sandbox_tier: 1",
        )

    argv = (row.get("payload", {}).get("arguments") or {}).get("argv")
    if not isinstance(argv, list) or not argv:
        raise HTTPException(
            status_code=400,
            detail="Interrupt carries no executable argv — deny it instead",
        )

    try:
        result = await run_tier1([str(a) for a in argv])
    except SandboxDenied as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    interrupt_table.delete(interrupt_id)
    bus.publish(TOOL_CALLED, {
        "type": "tool_called",
        "tool": row["payload"].get("tool", ""),
        "skill": row["skill_name"],
        "sandboxed": True,
        "argv": argv,
        "exit_code": result.exit_code,
    }, session_id=row.get("session_id", ""))
    bus.publish(INTERRUPT_RESOLVED, {
        "type": "interrupt_resolved",
        "interrupt_id": interrupt_id,
        "vector": str(InterruptVector.TOOL_EXEC_APPROVAL),
        "skill": row["skill_name"],
    }, session_id=row.get("session_id", ""))
    return {
        "status": "executed",
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
    }


@router.post("/interrupts/{interrupt_id}/deny", dependencies=[Depends(require_api_key)])
async def deny_exec_interrupt(interrupt_id: str):
    from core.bus.events import INTERRUPT_RESOLVED
    from core.kernel.interrupts import InterruptVector

    row = interrupt_table.get(interrupt_id)
    if not row or row.get("vector") != InterruptVector.TOOL_EXEC_APPROVAL:
        raise HTTPException(status_code=404, detail="No such exec interrupt")
    interrupt_table.delete(interrupt_id)
    bus.publish(INTERRUPT_RESOLVED, {
        "type": "interrupt_resolved",
        "interrupt_id": interrupt_id,
        "vector": str(InterruptVector.TOOL_EXEC_APPROVAL),
        "skill": row["skill_name"],
        "denied": True,
    }, session_id=row.get("session_id", ""))
    return {"status": "denied", "interrupt_id": interrupt_id}


class RecoveryRequest(BaseModel):
    path: str
    action: str  # mark_failed | dismiss


@router.get("/recovery")
async def list_recovery():
    from core.execution.recovery import scan_recovery

    return {"recovery": scan_recovery()}


@router.post("/recovery/resolve", dependencies=[Depends(require_api_key)])
async def resolve_recovery_item(request: RecoveryRequest):
    from core.execution.recovery import resolve_recovery

    try:
        found = resolve_recovery(request.path, request.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not found:
        raise HTTPException(status_code=404, detail="Loop note not found")
    return {"status": "resolved", "path": request.path, "action": request.action}


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


async def _resolve_approval(
    thread_id: str, approved: bool, modified_input: str | None = None
) -> dict:
    """Approve or reject one paused thread. Raises HTTPException if unresolvable."""
    pending = pending_threads.get(thread_id) or pending_store.get(thread_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Thread not found or already resolved")

    if not approved:
        obsidian.resolve_active_loop(
            pending["active_loop_path"],
            "terminated",
            note="Terminated by user",
        )
        obsidian.write_crash_report(
            thread_id, "Terminated by user", pending["skill_name"]
        )
        pending_threads.pop(thread_id, None)
        pending_store.delete(thread_id)
        bus.publish(RUN_TERMINATED, {
            "type": "execution_terminated",
            "thread_id": thread_id,
        }, session_id=pending["session_id"], thread_id=thread_id)
        telemetry.log_execution(thread_id, pending["skill_name"], "terminated")
        return {"status": "terminated", "thread_id": thread_id}

    graph = skill_registry.get(pending["skill_name"])
    if not graph:
        raise HTTPException(status_code=400, detail="Graph no longer registered")
    await graph.aupdate_state(
        pending["config"],
        {"approved": True, "modified_input": modified_input},
    )
    final_state = await graph.ainvoke(None, pending["config"])
    snapshot = await graph.aget_state(pending["config"])
    state_values = dict(snapshot.values) if snapshot.values else final_state

    result = await _finalize_execution(
        thread_id=thread_id,
        skill_name=pending["skill_name"],
        session_id=pending["session_id"],
        final_state=state_values,
        active_loop_path=pending["active_loop_path"],
        start=pending["start"],
        status_label="approved",
    )
    pending_threads.pop(thread_id, None)
    pending_store.delete(thread_id)
    return result


@router.post("/approve", dependencies=[Depends(require_api_key)])
async def approve_skill(request: ApprovalRequest):
    return await _resolve_approval(
        request.thread_id, request.approved, request.modified_input
    )


@router.post("/approve/batch", dependencies=[Depends(require_api_key)])
async def batch_approve(request: BatchApprovalRequest):
    """Resolve several paused threads in one call.

    Sequential on purpose: each approval resumes a graph (LLM calls), so the
    kernel scheduler still paces them. One thread failing never aborts the
    rest — each gets its own result row.
    """
    results = []
    ok = 0
    for thread_id in request.thread_ids:
        try:
            outcome = await _resolve_approval(thread_id, request.approved)
            results.append({"thread_id": thread_id, **outcome})
            ok += 1
        except HTTPException as exc:
            results.append({"thread_id": thread_id, "status": "error", "error": exc.detail})
        except Exception as exc:  # a bad graph must not sink the batch
            results.append({"thread_id": thread_id, "status": "error", "error": str(exc)})
    return {"requested": len(request.thread_ids), "resolved": ok, "results": results}
