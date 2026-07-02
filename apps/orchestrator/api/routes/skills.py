from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.websocket import ws_manager
from core.config import settings
from core.graphs.registry import SkillRegistry
from core.graphs.node_events import emit_node
from core.memory.obsidian_client import ObsidianClient
from core.memory.rag_engine import RAGEngine
from core.telemetry.store import TelemetryStore

router = APIRouter(prefix="/skills", tags=["skills"])

obsidian = ObsidianClient(settings.vault_path)
rag = RAGEngine(vault_path=settings.vault_path)
telemetry = TelemetryStore()
skill_registry = SkillRegistry(obsidian)

pending_threads: dict[str, dict[str, Any]] = {}


async def _fetch_skill_context(user_input: str, skill_config: dict[str, Any]) -> tuple[str, list[str]]:
    """Retrieve prospect context and knowledge-base context separately, then merge."""
    prospect_chunks = await rag.query(
        query_text=user_input,
        top_k=5,
        filter_metadata={"tags": skill_config.get("required_tags", [])},
    )
    knowledge_chunks = await rag.query(
        query_text=user_input,
        top_k=3,
        filter_metadata={"tags": skill_config.get("knowledge_tags", ["brand", "guidelines"])},
    )

    seen: set[str] = set()
    merged = []
    for chunk in prospect_chunks + knowledge_chunks:
        if chunk.source_path not in seen:
            seen.add(chunk.source_path)
            merged.append(chunk)

    system_context = await rag.summarize_context(merged)
    sources = [c.source_path for c in merged]
    return system_context, sources


async def _maybe_drift_alert(session_id: str, final_state: dict[str, Any]) -> None:
    messages = [
        getattr(m, "content", str(m)) for m in final_state.get("messages", [])
    ]
    if telemetry.detect_drift(messages):
        await ws_manager.broadcast(session_id, {
            "type": "drift_alert",
            "message": "Agent output appears cyclically repetitive — review results carefully",
        })


async def _maybe_cost_alert(session_id: str, cost: float) -> None:
    if cost >= settings.cost_alert_threshold:
        await ws_manager.broadcast(session_id, {
            "type": "cost_alert",
            "cost": cost,
            "threshold": settings.cost_alert_threshold,
        })


def _extract_result_content(final_state: dict[str, Any]) -> str:
    if final_state.get("messages"):
        last_msg = final_state["messages"][-1]
        return getattr(last_msg, "content", str(last_msg))
    return final_state.get("draft", "")


async def _finalize_execution(
    *,
    thread_id: str,
    skill_name: str,
    session_id: str,
    final_state: dict[str, Any],
    active_loop_path: str,
    start: float,
    status_label: str = "completed",
) -> dict[str, Any]:
    result_content = _extract_result_content(final_state)
    archive_path = obsidian.write_closeout_note(
        skill_name=skill_name,
        result=result_content,
        metadata={"cost": final_state.get("cost", 0)},
        confidence_score=final_state.get("confidence_score", 0.0),
        context_sources=final_state.get("context_sources", []),
        key_decisions=final_state.get("key_decisions", []),
        next_steps=["Human approval required for final send."],
    )

    obsidian.resolve_active_loop(
        active_loop_path,
        status_label,
        note=f"Archived to {archive_path.name}",
    )

    latency = int((time.monotonic() - start) * 1000)
    telemetry.log_execution(
        thread_id,
        skill_name,
        status_label,
        confidence_score=final_state.get("confidence_score", 0.0),
        input_tokens=final_state.get("input_tokens", 0),
        output_tokens=final_state.get("output_tokens", 0),
        cost=final_state.get("cost", 0.0),
        latency_ms=latency,
    )

    await _maybe_cost_alert(session_id, final_state.get("cost", 0.0))
    await _maybe_drift_alert(session_id, final_state)

    await ws_manager.broadcast(session_id, {
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
        "status": status_label,
        "thread_id": thread_id,
        "confidence_score": final_state.get("confidence_score"),
        "archive_path": str(archive_path),
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
    return {
        "skills": obsidian.list_skills(),
        "registered_graphs": skill_registry.list_registered(),
        "available_graph_types": SkillRegistry.available_graph_types(),
    }


@router.post("/reload")
async def reload_skills():
    """Re-scan vault skill definitions and refresh graph registry."""
    skill_registry.reload()
    return {
        "registered": skill_registry.list_registered(),
        "available_graph_types": SkillRegistry.available_graph_types(),
    }


@router.post("/execute")
async def execute_skill(request: SkillRequest):
    start = time.monotonic()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    skill_config = obsidian.read_skill_config(request.skill_name)
    if not skill_config:
        raise HTTPException(status_code=404, detail="Skill definition not found in Vault")

    system_context, context_sources = await _fetch_skill_context(
        request.user_input, skill_config
    )

    active_loop_path = obsidian.write_active_loop(
        thread_id, request.skill_name, request.user_input
    )

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
        "context_sources": context_sources,
        "key_decisions": [],
        "thread_id": thread_id,
        "session_id": request.session_id,
    }

    active_graph = skill_registry.get(request.skill_name)
    if not active_graph:
        raise HTTPException(
            status_code=400,
            detail=f"No graph registered for skill '{request.skill_name}'. "
            f"Available: {skill_registry.list_registered()}",
        )

    await ws_manager.broadcast(request.session_id, {
        "type": "execution_started",
        "thread_id": thread_id,
        "skill": request.skill_name,
        "context_sources": context_sources,
        "nodes": skill_config.get("nodes", []),
    })

    try:
        final_state = await active_graph.ainvoke(initial_state, config)
        snapshot = await active_graph.aget_state(config)
        state_values = dict(snapshot.values) if snapshot.values else final_state

        # Graph paused before human_approval — finalize has NOT run
        if snapshot.next and "human_approval" in snapshot.next:
            pending_threads[thread_id] = {
                "config": config,
                "session_id": request.session_id,
                "skill_name": request.skill_name,
                "active_loop_path": str(active_loop_path),
                "start": start,
            }
            obsidian.resolve_active_loop(
                active_loop_path,
                "awaiting_approval",
                note=f"Confidence {state_values.get('confidence_score', 0):.2f} — waiting for human",
            )
            await emit_node(
                request.session_id,
                "human_approval",
                "waiting",
                output=state_values.get("draft", ""),
            )
            await ws_manager.send_approval_request(
                request.session_id,
                thread_id,
                state_values.get("draft", ""),
                state_values.get("confidence_score", 0.0),
            )
            await _maybe_cost_alert(request.session_id, state_values.get("cost", 0.0))
            return {
                "status": "waiting_for_input",
                "thread_id": thread_id,
                "confidence_score": state_values.get("confidence_score"),
            }

        return await _finalize_execution(
            thread_id=thread_id,
            skill_name=request.skill_name,
            session_id=request.session_id,
            final_state=state_values,
            active_loop_path=str(active_loop_path),
            start=start,
        )

    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        obsidian.resolve_active_loop(active_loop_path, "failed", note=str(e))
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
        obsidian.resolve_active_loop(
            pending["active_loop_path"],
            "terminated",
            note="Terminated by user",
        )
        obsidian.write_crash_report(
            request.thread_id, "Terminated by user", pending["skill_name"]
        )
        del pending_threads[request.thread_id]
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

    del pending_threads[request.thread_id]
    return result
