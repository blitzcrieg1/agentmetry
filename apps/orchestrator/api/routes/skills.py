from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.websocket import ws_manager
from core.config import settings
from core.graphs.lead_gen_graph import lead_gen_graph
from core.memory.obsidian_client import ObsidianClient
from core.memory.rag_engine import RAGEngine
from core.telemetry.store import TelemetryStore

router = APIRouter(prefix="/skills", tags=["skills"])

obsidian = ObsidianClient(settings.vault_path)
rag = RAGEngine(vault_path=settings.vault_path)
telemetry = TelemetryStore()

# In-memory thread state for human-in-the-loop
pending_threads: dict[str, dict[str, Any]] = {}

GRAPH_REGISTRY = {
    "lead_gen": lead_gen_graph,
}


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
    return {"skills": obsidian.list_skills()}


@router.post("/execute")
async def execute_skill(request: SkillRequest):
    start = time.monotonic()
    thread_id = str(uuid.uuid4())

    skill_config = obsidian.read_skill_config(request.skill_name)
    if not skill_config:
        raise HTTPException(status_code=404, detail="Skill definition not found in Vault")

    context_chunks = await rag.query(
        query_text=request.user_input,
        top_k=5,
        filter_metadata={"tags": skill_config.get("required_tags", [])},
    )
    system_context = await rag.summarize_context(context_chunks)

    initial_state: dict[str, Any] = {
        "user_input": request.user_input,
        "system_context": system_context,
        "skill_config": skill_config,
        "messages": [],
        "requires_approval": False,
        "approved": None,
        "modified_input": None,
        "cost": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "context_sources": [],
        "key_decisions": [],
        "thread_id": thread_id,
    }

    active_graph = GRAPH_REGISTRY.get(request.skill_name)
    if not active_graph:
        raise HTTPException(status_code=400, detail=f"Graph not implemented: {request.skill_name}")

    await ws_manager.broadcast(request.session_id, {
        "type": "execution_started",
        "thread_id": thread_id,
        "skill": request.skill_name,
    })

    try:
        final_state = await active_graph.ainvoke(initial_state)

        if final_state.get("requires_approval") and final_state.get("approved") is None:
            pending_threads[thread_id] = {
                "state": final_state,
                "session_id": request.session_id,
                "skill_name": request.skill_name,
            }
            await ws_manager.send_approval_request(
                request.session_id,
                thread_id,
                final_state.get("draft", ""),
                final_state.get("confidence_score", 0.0),
            )
            return {
                "status": "waiting_for_input",
                "thread_id": thread_id,
                "confidence_score": final_state.get("confidence_score"),
            }

        result_content = ""
        if final_state.get("messages"):
            last_msg = final_state["messages"][-1]
            result_content = getattr(last_msg, "content", str(last_msg))

        archive_path = obsidian.write_closeout_note(
            skill_name=request.skill_name,
            result=result_content,
            metadata={"cost": final_state.get("cost", 0)},
            confidence_score=final_state.get("confidence_score", 0.0),
            context_sources=final_state.get("context_sources", []),
            key_decisions=final_state.get("key_decisions", []),
            next_steps=["Human approval required for final send."],
        )

        latency = int((time.monotonic() - start) * 1000)
        telemetry.log_execution(
            thread_id,
            request.skill_name,
            "completed",
            confidence_score=final_state.get("confidence_score", 0.0),
            input_tokens=final_state.get("input_tokens", 0),
            output_tokens=final_state.get("output_tokens", 0),
            cost=final_state.get("cost", 0.0),
            latency_ms=latency,
        )

        await ws_manager.broadcast(request.session_id, {
            "type": "execution_completed",
            "thread_id": thread_id,
            "archive_path": str(archive_path),
            "metrics": {
                "cost": final_state.get("cost", 0),
                "input_tokens": final_state.get("input_tokens", 0),
                "output_tokens": final_state.get("output_tokens", 0),
                "latency_ms": latency,
            },
        })

        return {
            "status": "completed",
            "thread_id": thread_id,
            "confidence_score": final_state.get("confidence_score"),
            "archive_path": str(archive_path),
        }

    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        telemetry.log_execution(
            thread_id, request.skill_name, "failed", latency_ms=latency, error=str(e)
        )
        await ws_manager.broadcast(request.session_id, {
            "type": "execution_failed",
            "thread_id": thread_id,
            "error": str(e),
        })
        return {"status": "failed", "thread_id": thread_id, "error": str(e)}


@router.post("/approve")
async def approve_skill(request: ApprovalRequest):
    pending = pending_threads.get(request.thread_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Thread not found or already resolved")

    if not request.approved:
        obsidian.write_crash_report(
            request.thread_id, "Terminated by user", pending["skill_name"]
        )
        del pending_threads[request.thread_id]
        await ws_manager.broadcast(pending["session_id"], {
            "type": "execution_terminated",
            "thread_id": request.thread_id,
        })
        return {"status": "terminated", "thread_id": request.thread_id}

    state = pending["state"]
    state["approved"] = True
    if request.modified_input:
        state["modified_input"] = request.modified_input

    from core.graphs.lead_gen_graph import finalize_node

    final = await finalize_node(state)
    result_content = final["messages"][-1].content

    archive_path = obsidian.write_closeout_note(
        skill_name=pending["skill_name"],
        result=result_content,
        metadata={"cost": state.get("cost", 0)},
        confidence_score=state.get("confidence_score", 0.0),
        context_sources=state.get("context_sources", []),
        key_decisions=state.get("key_decisions", []),
    )

    del pending_threads[request.thread_id]

    await ws_manager.broadcast(pending["session_id"], {
        "type": "execution_completed",
        "thread_id": request.thread_id,
        "archive_path": str(archive_path),
    })

    return {
        "status": "approved",
        "thread_id": request.thread_id,
        "archive_path": str(archive_path),
    }
