"""Skill execution service — shared by API routes and autonomous triggers."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from core.bus.bus import bus
from core.bus.events import (
    ALERT_COST,
    ALERT_DRIFT,
    INTERRUPT_RAISED,
    INTERRUPT_RESOLVED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_WAITING,
)
from core.config import settings
from core.execution.context import (
    interrupt_table,
    obsidian,
    pending_store,
    pending_threads,
    rag,
    skill_registry,
    telemetry,
)
from core.graphs.node_events import emit_node
from core.kernel.interrupts import InterruptVector
from core.kernel.scheduler import Priority, get_scheduler, run_priority
from core.llm.budget import get_budget_ledger
from core.llm.degraded import llm_degraded
from core.llm.errors import CostBudgetExceeded
from core.notifiers.audit import append_vault_run_log, log_run
from core.notifiers.toast import notify

logger = logging.getLogger(__name__)

# Guard against pathological trigger notes blowing up the prompt.
_TRIGGER_NOTE_MAX_CHARS = 50_000


def _latency_ms(start_epoch: float) -> int:
    """Elapsed ms since a wall-clock start; 0 when the start is garbage.

    Pending threads persist their start across restarts — rows written by
    older builds stored time.monotonic(), which is meaningless after a boot.
    """
    elapsed = time.time() - start_epoch
    if 0 <= elapsed < 30 * 86400:
        return int(elapsed * 1000)
    return 0


def _inject_trigger_note(
    system_context: str,
    context_sources: list[str],
    trigger_file_path: str,
    *,
    client: Any = None,
) -> tuple[str, list[str]]:
    """Prepend the full content of the note that fired a trigger.

    Triggered skills must act on the actual triggering note, not on whatever
    RAG happens to retrieve for the rendered template text.
    """
    vault = client or obsidian
    note = vault.read_note(trigger_file_path)
    if note is None:
        logger.warning("Trigger note not readable, skipping injection: %s", trigger_file_path)
        return system_context, context_sources
    header = f"[Source: {trigger_file_path}] (triggering note — full content)"
    system_context = f"{header}\n{note[:_TRIGGER_NOTE_MAX_CHARS]}\n\n{system_context}"
    if trigger_file_path not in context_sources:
        context_sources = [trigger_file_path, *context_sources]
    return system_context, context_sources


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


async def resume_deferred_interrupts() -> dict[str, int]:
    """Retry budget- and degradation-deferred autonomous runs when gates clear."""
    counts = {"budget": 0, "degraded": 0}
    ledger = get_budget_ledger()
    budget_ok = ledger.autonomous_allowed()
    degraded_ok = not llm_degraded.active

    if not budget_ok and not degraded_ok:
        return counts

    vectors: list[tuple[InterruptVector, bool, str]] = [
        (InterruptVector.BUDGET_DEFER, budget_ok, "budget"),
        (InterruptVector.LLM_DEGRADED, degraded_ok, "degraded"),
    ]
    for vector, allowed, key in vectors:
        if not allowed:
            continue
        for row in list(interrupt_table.list_pending(vector)):
            interrupt_id = row["interrupt_id"]
            interrupt_table.delete(interrupt_id)
            bus.publish(INTERRUPT_RESOLVED, {
                "type": "interrupt_resolved",
                "interrupt_id": interrupt_id,
                "vector": str(vector),
                "skill": row["skill_name"],
            }, session_id=row["session_id"])
            result = await run_skill(
                row["skill_name"],
                row["user_input"],
                row["session_id"],
                triggered_by=row["triggered_by"],
                trigger_rule_id=row.get("trigger_rule_id"),
                trigger_file_path=row.get("trigger_file_path"),
            )
            if result.get("status") not in ("deferred_budget", "deferred_degraded"):
                counts[key] += 1
    if counts["budget"] or counts["degraded"]:
        logger.info(
            "Resumed deferred interrupts — budget: %d, degraded: %d",
            counts["budget"],
            counts["degraded"],
        )
    return counts


async def recover_interrupts() -> dict[str, int]:
    """Reload HITL threads and resume deferred autonomous work on startup."""
    hitl = await recover_pending_threads()
    deferred = await resume_deferred_interrupts()
    return {
        "hitl": hitl,
        "budget_defer_resumed": deferred["budget"],
        "llm_degraded_resumed": deferred["degraded"],
    }


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


def _maybe_drift_alert(session_id: str, final_state: dict[str, Any]) -> None:
    messages = [getattr(m, "content", str(m)) for m in final_state.get("messages", [])]
    if telemetry.detect_drift(messages):
        bus.publish(ALERT_DRIFT, {
            "type": "drift_alert",
            "message": "Agent output appears cyclically repetitive — review results carefully",
        }, session_id=session_id)


def _maybe_cost_alert(session_id: str, cost: float) -> None:
    if cost >= settings.cost_alert_threshold:
        bus.publish(ALERT_COST, {
            "type": "cost_alert",
            "cost": cost,
            "threshold": settings.cost_alert_threshold,
        }, session_id=session_id)


def _budget_exceeded_result(
    *,
    thread_id: str,
    skill_name: str,
    session_id: str,
    active_loop_path: str,
    triggered_by: str,
    trigger_rule_id: str | None,
    cost: float,
    max_cost: float,
    start: float,
) -> dict[str, Any]:
    obsidian.resolve_active_loop(
        active_loop_path,
        "budget_exceeded",
        note=f"Cost ${cost:.4f} exceeded max ${max_cost:.4f}",
    )
    latency = _latency_ms(start)
    telemetry.log_execution(
        thread_id, skill_name, "budget_exceeded", cost=cost, latency_ms=latency
    )
    log_run({
        "thread_id": thread_id,
        "skill": skill_name,
        "status": "budget_exceeded",
        "triggered_by": triggered_by,
        "trigger_rule_id": trigger_rule_id,
        "session_id": session_id,
        "cost": cost,
        "max_cost_per_run": max_cost,
    })
    bus.publish(RUN_FAILED, {
        "type": "execution_failed",
        "thread_id": thread_id,
        "error": f"Cost ${cost:.4f} exceeded max ${max_cost:.4f}",
        "status": "budget_exceeded",
    }, session_id=session_id, thread_id=thread_id)
    return {
        "status": "budget_exceeded",
        "thread_id": thread_id,
        "cost": cost,
        "max_cost_per_run": max_cost,
    }


def _extract_result_content(final_state: dict[str, Any]) -> str:
    if final_state.get("messages"):
        last_msg = final_state["messages"][-1]
        return getattr(last_msg, "content", str(last_msg))
    return (
        final_state.get("draft", "")
        or final_state.get("output", "")
        or final_state.get("summary", "")
    )


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
    llm_providers = list(final_state.get("llm_providers") or [])
    archive_path = obsidian.write_closeout_note(
        skill_name=skill_name,
        result=result_content,
        metadata={
            "cost": final_state.get("cost", 0),
            "llm_providers": llm_providers,
        },
        thread_id=thread_id,
        status="mock-dry-run" if "mock" in llm_providers else "success",
        confidence_score=final_state.get("confidence_score", 0.0),
        context_sources=final_state.get("context_sources", []),
        key_decisions=final_state.get("key_decisions", []),
        next_steps=final_state.get("next_steps", []),
    )

    obsidian.resolve_active_loop(
        active_loop_path,
        status_label,
        note=f"Archived to {archive_path.name}",
    )

    latency = _latency_ms(start)
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
        "session_id": session_id,
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

    _maybe_cost_alert(session_id, cost)
    _maybe_drift_alert(session_id, final_state)

    bus.publish(RUN_COMPLETED, {
        "type": "execution_completed",
        "thread_id": thread_id,
        "archive_path": str(archive_path),
        "metrics": {
            "cost": cost,
            "input_tokens": final_state.get("input_tokens", 0),
            "output_tokens": final_state.get("output_tokens", 0),
            "latency_ms": latency,
        },
    }, session_id=session_id, thread_id=thread_id)

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
    trigger_file_path: str | None = None,
) -> dict[str, Any]:
    """Execute a skill graph. Used by HTTP API and autonomous triggers."""
    if llm_degraded.active and settings.llm_provider.lower() == "gemini":
        if triggered_by != "manual":
            interrupt = interrupt_table.raise_llm_degraded(
                skill_name=skill_name,
                session_id=session_id,
                user_input=user_input,
                triggered_by=triggered_by,
                trigger_rule_id=trigger_rule_id,
                trigger_file_path=trigger_file_path,
                reason=llm_degraded.reason,
            )
            bus.publish(INTERRUPT_RAISED, {
                "type": "interrupt_raised",
                "interrupt_id": interrupt["interrupt_id"],
                "vector": InterruptVector.LLM_DEGRADED,
                "skill": skill_name,
            }, session_id=session_id)
            log_run({
                "skill": skill_name,
                "status": "deferred_degraded",
                "triggered_by": triggered_by,
                "trigger_rule_id": trigger_rule_id,
                "session_id": session_id,
                "interrupt_id": interrupt["interrupt_id"],
                "reason": llm_degraded.reason,
            })
            return {
                "status": "deferred_degraded",
                "interrupt_id": interrupt["interrupt_id"],
                "resumable": True,
                "reason": llm_degraded.reason,
            }
        msg = f"LLM degraded: {llm_degraded.reason}"
        log_run({
            "skill": skill_name,
            "status": "rejected",
            "triggered_by": triggered_by,
            "trigger_rule_id": trigger_rule_id,
            "session_id": session_id,
            "error": msg,
        })
        return {"status": "rejected", "error": msg, "degraded": True}

    # Autonomous runs pause once only the interactive Flash reserve is left;
    # manual runs always proceed (a real 429 still trips degraded mode).
    if triggered_by != "manual" and settings.llm_provider.lower() == "gemini":
        ledger = get_budget_ledger()
        if not ledger.autonomous_allowed():
            snapshot = ledger.snapshot()
            interrupt = interrupt_table.raise_budget_defer(
                skill_name=skill_name,
                session_id=session_id,
                user_input=user_input,
                triggered_by=triggered_by,
                trigger_rule_id=trigger_rule_id,
                trigger_file_path=trigger_file_path,
                budget_snapshot=snapshot,
            )
            bus.publish(INTERRUPT_RAISED, {
                "type": "interrupt_raised",
                "interrupt_id": interrupt["interrupt_id"],
                "vector": InterruptVector.BUDGET_DEFER,
                "skill": skill_name,
                "budget": snapshot,
            }, session_id=session_id)
            logger.info(
                "Deferring autonomous run of %s — %d/%d Flash calls used today",
                skill_name, snapshot["flash_used"], snapshot["flash_limit"],
            )
            log_run({
                "skill": skill_name,
                "status": "deferred_budget",
                "triggered_by": triggered_by,
                "trigger_rule_id": trigger_rule_id,
                "session_id": session_id,
                "interrupt_id": interrupt["interrupt_id"],
                "budget": snapshot,
            })
            return {
                "status": "deferred_budget",
                "interrupt_id": interrupt["interrupt_id"],
                "resumable": True,
                "budget": snapshot,
            }

    # Kernel priority for every LLM/embed grant in this run. Task-scoped
    # context: API handlers, cron jobs, and watcher work each run in their
    # own task, so this cannot leak into unrelated work.
    run_priority.set(
        Priority.INTERACTIVE if triggered_by == "manual" else Priority.AUTONOMOUS
    )

    # Run admission lives in the kernel: interactive runs start immediately,
    # background runs share a bounded pool (kernel_background_run_limit).
    async with get_scheduler().run_slot():
        start = time.time()
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        skill_config = obsidian.read_skill_config(skill_name)
        if not skill_config:
            return {"status": "failed", "error": f"Skill '{skill_name}' not found in vault"}

        max_cost = skill_config.get("max_cost_per_run")
        if max_cost is not None and float(max_cost) <= 0:
            return {"status": "failed", "error": "Invalid max_cost_per_run in skill config"}

        system_context, context_sources = await _fetch_skill_context(user_input, skill_config)
        if trigger_file_path:
            system_context, context_sources = _inject_trigger_note(
                system_context, context_sources, trigger_file_path
            )

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
            "llm_providers": [],
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

        bus.publish(RUN_STARTED, {
            "type": "execution_started",
            "thread_id": thread_id,
            "skill": skill_name,
            "context_sources": context_sources,
            "nodes": skill_config.get("nodes", []),
            "triggered_by": triggered_by,
        }, session_id=session_id, thread_id=thread_id)

        try:
            final_state = await active_graph.ainvoke(initial_state, config)
            snapshot = await active_graph.aget_state(config)
            state_values = dict(snapshot.values) if snapshot.values else final_state

            run_cost = float(state_values.get("cost", 0.0))
            if max_cost is not None and run_cost > float(max_cost):
                return _budget_exceeded_result(
                    thread_id=thread_id,
                    skill_name=skill_name,
                    session_id=session_id,
                    active_loop_path=str(active_loop_path),
                    triggered_by=triggered_by,
                    trigger_rule_id=trigger_rule_id,
                    cost=run_cost,
                    max_cost=float(max_cost),
                    start=start,
                )

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
                    thread_id,
                    "human_approval",
                    "waiting",
                    output=state_values.get("draft", ""),
                )
                bus.publish(RUN_WAITING, {
                    "type": "approval_required",
                    "thread_id": thread_id,
                    "draft": state_values.get("draft", ""),
                    "confidence": state_values.get("confidence_score", 0.0),
                    "status": "waiting_for_input",
                }, session_id=session_id, thread_id=thread_id)
                _maybe_cost_alert(session_id, run_cost)
                log_run({
                    "thread_id": thread_id,
                    "skill": skill_name,
                    "status": "waiting_for_input",
                    "triggered_by": triggered_by,
                    "trigger_rule_id": trigger_rule_id,
                    "session_id": session_id,
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

        except CostBudgetExceeded as exc:
            return _budget_exceeded_result(
                thread_id=thread_id,
                skill_name=skill_name,
                session_id=session_id,
                active_loop_path=str(active_loop_path),
                triggered_by=triggered_by,
                trigger_rule_id=trigger_rule_id,
                cost=exc.cost,
                max_cost=exc.max_cost,
                start=start,
            )
        except Exception as e:
            latency = _latency_ms(start)
            obsidian.resolve_active_loop(active_loop_path, "failed", note=str(e))
            telemetry.log_execution(
                thread_id, skill_name, "failed", latency_ms=latency, error=str(e)
            )
            log_run({
                "thread_id": thread_id,
                "skill": skill_name,
                "status": "failed",
                "triggered_by": triggered_by,
                "session_id": session_id,
                "error": str(e),
            })
            bus.publish(RUN_FAILED, {
                "type": "execution_failed",
                "thread_id": thread_id,
                "error": str(e),
            }, session_id=session_id, thread_id=thread_id)
            return {"status": "failed", "thread_id": thread_id, "error": str(e)}
