"""Skill execution service — shared by API routes and autonomous triggers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from api.websocket import ws_manager
from core.config import settings
from core.execution.context import (
    obsidian,
    pending_store,
    pending_threads,
    rag,
    skill_registry,
    telemetry,
)
from core.graphs.node_events import emit_node
from core.llm.degraded import llm_degraded
from core.notifiers.audit import append_vault_run_log, log_run
from core.notifiers.toast import notify

logger = logging.getLogger(__name__)

_run_semaphore = asyncio.Semaphore(2)


async def recover_pending_threads() -> int:
    """Reload pending approval threads from durable storage after restart."""
    pending_threads.clear()
    recovered = 0
    for row in pending_store.list_all():
        graph = skill_registry.get(row["skill_name"])
        if not graph:
            pending_store.delete(row["thread_id"])
            continue
        try:
            snapshot = await graph.aget_state(row["config"])
            if snapshot.next and "human_approval" in snapshot.next:
                pending_threads[row["thread_id"]] = row
                recovered += 1
            else:
                pending_store.delete(row["thread_id"])
        except Exception:
            pending_store.delete(row["thread_id"])
    if recovered:
        logger.info("Recovered %d pending approval thread(s)", recovered)
    return recovered


async def _fetch_skill_context(user_input: str, skill_config: dict[str, Any]) -> tuple[str, list[str]]:
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
    messages = [getattr(m, "content", str(m)) for m in final_state.get("messages", [])]
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
    return final_state.get("draft", "") or final_state.get("summary", "")


async def _finalize_execution(
    *,
    thread_id: str,
    skill_name: str,
    session_id: str,
    final_state: dict[str, Any],
    active_loop_path: str,
    start: float,
    status_label: str = "completed",
    triggered_by: str = "manual",
    trigger_rule_id: str | None = None,
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
    cost = final_state.get("cost", 0.0)
    telemetry.log_execution(
        thread_id,
        skill_name,
        status_label,
        confidence_score=final_state.get("confidence_score", 0.0),
        input_tokens=final_state.get("input_tokens", 0),
        output_tokens=final_state.get("output_tokens", 0),
        cost=cost,
        latency_ms=latency,
    )

    log_run({
        "thread_id": thread_id,
        "skill": skill_name,
        "status": status_label,
        "triggered_by": triggered_by,
        "trigger_rule_id": trigger_rule_id,
        "cost": cost,
        "latency_ms": latency,
        "archive_path": str(archive_path),
    })
    append_vault_run_log(
        f"`{skill_name}` ({triggered_by}) → {status_label} — ${cost:.4f}, {latency}ms"
    )

    if triggered_by != "manual":
        notify(
            "BLACKBOX",
            f"{skill_name} {status_label} (${cost:.4f})",
        )

    await _maybe_cost_alert(session_id, cost)
    await _maybe_drift_alert(session_id, final_state)

    await ws_manager.broadcast(session_id, {
        "type": "execution_completed",
        "thread_id": thread_id,
        "archive_path": str(archive_path),
        "metrics": {
            "cost": cost,
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


async def run_skill(
    skill_name: str,
    user_input: str,
    session_id: str,
    *,
    triggered_by: str = "manual",
    trigger_rule_id: str | None = None,
) -> dict[str, Any]:
    """Execute a skill graph. Used by HTTP API and autonomous triggers."""
    if llm_degraded.active and settings.llm_provider.lower() == "gemini":
        msg = f"LLM degraded: {llm_degraded.reason}"
        log_run({
            "skill": skill_name,
            "status": "rejected",
            "triggered_by": triggered_by,
            "trigger_rule_id": trigger_rule_id,
            "error": msg,
        })
        return {"status": "rejected", "error": msg, "degraded": True}

    async with _run_semaphore:
        start = time.monotonic()
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        skill_config = obsidian.read_skill_config(skill_name)
        if not skill_config:
            return {"status": "failed", "error": f"Skill '{skill_name}' not found in vault"}

        max_cost = skill_config.get("max_cost_per_run")
        if max_cost is not None and float(max_cost) <= 0:
            return {"status": "failed", "error": "Invalid max_cost_per_run in skill config"}

        system_context, context_sources = await _fetch_skill_context(user_input, skill_config)

        active_loop_path = obsidian.write_active_loop(
            thread_id,
            skill_name,
            user_input,
            nodes=skill_config.get("nodes"),
        )

        initial_state: dict[str, Any] = {
            "user_input": user_input,
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
            "session_id": session_id,
        }

        active_graph = skill_registry.get(skill_name)
        if not active_graph:
            return {
                "status": "failed",
                "error": f"No graph registered for skill '{skill_name}'",
            }

        await ws_manager.broadcast(session_id, {
            "type": "execution_started",
            "thread_id": thread_id,
            "skill": skill_name,
            "context_sources": context_sources,
            "nodes": skill_config.get("nodes", []),
            "triggered_by": triggered_by,
        })

        try:
            final_state = await active_graph.ainvoke(initial_state, config)
            snapshot = await active_graph.aget_state(config)
            state_values = dict(snapshot.values) if snapshot.values else final_state

            run_cost = float(state_values.get("cost", 0.0))
            if max_cost is not None and run_cost > float(max_cost):
                obsidian.resolve_active_loop(
                    active_loop_path,
                    "budget_exceeded",
                    note=f"Cost ${run_cost:.4f} exceeded max ${float(max_cost):.4f}",
                )
                log_run({
                    "thread_id": thread_id,
                    "skill": skill_name,
                    "status": "budget_exceeded",
                    "triggered_by": triggered_by,
                    "cost": run_cost,
                    "max_cost_per_run": max_cost,
                })
                return {
                    "status": "budget_exceeded",
                    "thread_id": thread_id,
                    "cost": run_cost,
                    "max_cost_per_run": max_cost,
                }

            if snapshot.next and "human_approval" in snapshot.next:
                pending_meta = {
                    "config": config,
                    "session_id": session_id,
                    "skill_name": skill_name,
                    "active_loop_path": str(active_loop_path),
                    "start": start,
                }
                pending_threads[thread_id] = pending_meta
                pending_store.save(
                    thread_id,
                    skill_name=skill_name,
                    session_id=session_id,
                    active_loop_path=str(active_loop_path),
                    config=config,
                    start=start,
                )
                obsidian.resolve_active_loop(
                    active_loop_path,
                    "awaiting_approval",
                    note=f"Confidence {state_values.get('confidence_score', 0):.2f} — waiting for human",
                )
                await emit_node(
                    session_id,
                    "human_approval",
                    "waiting",
                    output=state_values.get("draft", ""),
                )
                await ws_manager.send_approval_request(
                    session_id,
                    thread_id,
                    state_values.get("draft", ""),
                    state_values.get("confidence_score", 0.0),
                )
                await _maybe_cost_alert(session_id, run_cost)
                log_run({
                    "thread_id": thread_id,
                    "skill": skill_name,
                    "status": "waiting_for_input",
                    "triggered_by": triggered_by,
                    "trigger_rule_id": trigger_rule_id,
                })
                return {
                    "status": "waiting_for_input",
                    "thread_id": thread_id,
                    "confidence_score": state_values.get("confidence_score"),
                }

            return await _finalize_execution(
                thread_id=thread_id,
                skill_name=skill_name,
                session_id=session_id,
                final_state=state_values,
                active_loop_path=str(active_loop_path),
                start=start,
                triggered_by=triggered_by,
                trigger_rule_id=trigger_rule_id,
            )

        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            obsidian.resolve_active_loop(active_loop_path, "failed", note=str(e))
            telemetry.log_execution(
                thread_id, skill_name, "failed", latency_ms=latency, error=str(e)
            )
            log_run({
                "thread_id": thread_id,
                "skill": skill_name,
                "status": "failed",
                "triggered_by": triggered_by,
                "error": str(e),
            })
            await ws_manager.broadcast(session_id, {
                "type": "execution_failed",
                "thread_id": thread_id,
                "error": str(e),
            })
            return {"status": "failed", "thread_id": thread_id, "error": str(e)}
