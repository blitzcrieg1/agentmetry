"""Skill execution service — shared by API routes and autonomous triggers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from core.audit.run_context import (
    audit_payload,
    clear_run_context,
    last_gated_action,
    set_thread_initiator,
)
from core.bus.bus import bus
from core.bus.events import (
    ALERT_COST,
    ALERT_DRIFT,
    INTERRUPT_RAISED,
    INTERRUPT_RESOLVED,
    RUN_APPROVAL_DENIED,
    RUN_APPROVAL_GRANTED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_TERMINATED,
    RUN_WAITING,
)
from core.config import settings
from core.execution.context import (
    fts,
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
from core.learning.flywheel import schedule_edit_capture
from core.llm.budget import get_budget_ledger
from core.llm.degraded import llm_degraded
from core.llm.errors import CostBudgetExceeded
from core.memory.obsidian_client import ObsidianClient
from core.notifiers.audit import append_vault_run_log, log_run
from core.notifiers.toast import notify

logger = logging.getLogger(__name__)

# Guard against pathological trigger notes blowing up the prompt.
_TRIGGER_NOTE_MAX_CHARS = 50_000
_SOP_CONTEXT_MAX_CHARS = 4_000


def _resolve_sop_paths(
    skill_config: dict[str, Any], vault_path: Path | None = None
) -> list[str]:
    """Expand skill-configured SOP paths and globs to vault-relative markdown files."""
    vault = Path(vault_path or settings.vault_path)
    configured = skill_config.get("sop_paths") or []
    resolved: list[str] = []
    seen: set[str] = set()
    for entry in configured:
        rel = str(entry).replace("\\", "/").lstrip("/")
        if any(ch in rel for ch in "*?[]"):
            for match in sorted(vault.glob(rel)):
                if match.is_file() and match.suffix.lower() == ".md":
                    path = match.relative_to(vault).as_posix()
                    if path not in seen:
                        seen.add(path)
                        resolved.append(path)
            continue
        if (vault / rel).is_file() and rel not in seen:
            seen.add(rel)
            resolved.append(rel)
    return resolved


def _append_sop_context(
    blocks: list[str],
    sources: list[str],
    skill_config: dict[str, Any],
    *,
    vault_path: Path | None = None,
) -> None:
    """Inject full SOP text before FTS/RAG so reply skills follow vault policy."""
    if not skill_config.get("sop_paths"):
        return
    reader = obsidian if vault_path is None else ObsidianClient(vault_path)
    for rel in _resolve_sop_paths(skill_config, vault_path):
        if rel in sources:
            continue
        text = reader.read_note(rel)
        if not text:
            continue
        sources.append(rel)
        blocks.append(f"[SOP: {rel}]\n{text[:_SOP_CONTEXT_MAX_CHARS]}")


def _interactive(triggered_by: str) -> bool:
    """A human is actively waiting: manual API/dashboard runs and channel commands.

    Interactive runs get kernel INTERACTIVE priority and skip the autonomous
    budget/degraded deferral gates (same contract the dashboard already has).
    """
    return triggered_by == "manual" or triggered_by.startswith("channel:")


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
    import os

    from core.execution.recovery import (
        archive_resolved_loops_on_startup,
        report_recovery_on_startup,
        resume_orphans_on_startup,
    )

    hitl = await recover_pending_threads()
    deferred = await resume_deferred_interrupts()

    # Opt-in checkpoint resume for crashed mid-run work; manual resume via
    # the recovery panel / CLI is always available regardless of this flag.
    auto_resumed = 0
    if os.environ.get("BLACKBOX_AUTO_RESUME", "").strip() in ("1", "true", "yes"):
        auto_resumed = await resume_orphans_on_startup()

    archived = archive_resolved_loops_on_startup()
    stale = report_recovery_on_startup()
    return {
        "hitl": hitl,
        "budget_defer_resumed": deferred["budget"],
        "llm_degraded_resumed": deferred["degraded"],
        "auto_resumed": auto_resumed,
        "archived_loops": archived,
        "stale_loops": stale,
    }


async def _fetch_skill_context(user_input: str, skill_config: dict[str, Any]) -> tuple[str, list[str]]:
    sources: list[str] = []
    blocks: list[str] = []

    for rel in (".system/GOALS.md", ".system/AGENTS.md"):
        text = obsidian.read_note(rel)
        if text:
            sources.append(rel)
            blocks.append(f"[Source: {rel}]\n{text[:2500]}")

    _append_sop_context(blocks, sources, skill_config)

    for hit in fts.search(user_input, limit=5):
        path = hit["path"]
        if path in sources:
            continue
        sources.append(path)
        blocks.append(f"[Source: {path}]\n{hit['snippet']}")

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

    seen: set[str] = set(sources)
    merged = []
    for chunk in prospect_chunks + knowledge_chunks:
        if chunk.source_path not in seen:
            seen.add(chunk.source_path)
            merged.append(chunk)

    rag_context = await rag.summarize_context(merged)
    if rag_context:
        blocks.append(rag_context)
        sources.extend(c.source_path for c in merged)

    system_context = "\n\n".join(blocks)
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
        **audit_payload(thread_id, triggered_by),
    }, session_id=session_id, thread_id=thread_id)
    clear_run_context(thread_id)
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
    skill_config = final_state.get("skill_config") or {}
    metadata = {
        "cost": final_state.get("cost", 0),
        "llm_providers": llm_providers,
    }
    if skill_config.get("learning_archive"):
        archive_path = obsidian.write_sop_learning_patch(
            result_content,
            skill_name=skill_name,
            thread_id=thread_id,
            metadata=metadata,
            confidence_score=final_state.get("confidence_score", 0.0),
            context_sources=final_state.get("context_sources", []),
        )
    else:
        archive_path = obsidian.write_closeout_note(
            skill_name=skill_name,
            result=result_content,
            metadata=metadata,
            thread_id=thread_id,
            status="mock-dry-run" if "mock" in llm_providers else "success",
            confidence_score=final_state.get("confidence_score", 0.0),
            context_sources=final_state.get("context_sources", []),
            key_decisions=final_state.get("key_decisions", []),
            next_steps=final_state.get("next_steps", []),
            archive_subdir=skill_config.get("archive_subdir"),
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
        **audit_payload(thread_id, triggered_by),
    }, session_id=session_id, thread_id=thread_id)
    clear_run_context(thread_id)

    return {
        "status": status_label,
        "thread_id": thread_id,
        "confidence_score": final_state.get("confidence_score"),
        "archive_path": str(archive_path),
    }


class ApprovalNotFound(LookupError):
    """The thread does not exist or was already resolved."""


class ApprovalUnavailable(RuntimeError):
    """The thread exists but its graph is no longer registered."""


async def resolve_approval(
    thread_id: str, approved: bool, modified_input: str | None = None
) -> dict[str, Any]:
    """Approve or reject one paused thread.

    Transport-agnostic: the HTTP route and channel adapters (Telegram, ...)
    both resolve approvals through this single path so audit, archive, and
    pending-store bookkeeping never diverge.
    """
    pending = pending_threads.get(thread_id) or pending_store.get(thread_id)
    if not pending:
        raise ApprovalNotFound("Thread not found or already resolved")

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
        bus.publish(RUN_APPROVAL_DENIED, {
            "type": "approval_denied",
            "thread_id": thread_id,
            "skill": pending["skill_name"],
            **audit_payload(thread_id),
        }, session_id=pending["session_id"], thread_id=thread_id)
        bus.publish(RUN_TERMINATED, {
            "type": "execution_terminated",
            "thread_id": thread_id,
            **audit_payload(thread_id),
        }, session_id=pending["session_id"], thread_id=thread_id)
        clear_run_context(thread_id)
        telemetry.log_execution(thread_id, pending["skill_name"], "terminated")
        return {"status": "terminated", "thread_id": thread_id}

    graph = skill_registry.get(pending["skill_name"])
    if not graph:
        raise ApprovalUnavailable("Graph no longer registered")

    snapshot = await graph.aget_state(pending["config"])
    state_values = dict(snapshot.values) if snapshot.values else {}
    original_draft = str(state_values.get("draft") or "")
    if not original_draft:
        row = interrupt_table.get(thread_id)
        original_draft = str(((row or {}).get("payload") or {}).get("draft") or "")

    edited = bool(modified_input and modified_input.strip() != original_draft.strip())
    await schedule_edit_capture(
        thread_id=thread_id,
        skill_name=pending["skill_name"],
        session_id=pending["session_id"],
        original_draft=original_draft,
        modified_input=modified_input,
        client=obsidian,
    )

    bus.publish(RUN_APPROVAL_GRANTED, {
        "type": "approval_granted",
        "thread_id": thread_id,
        "skill": pending["skill_name"],
        "edited": edited,
        **audit_payload(thread_id),
    }, session_id=pending["session_id"], thread_id=thread_id)

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
    if llm_degraded.active and llm_degraded.retry_elapsed():
        llm_degraded.clear()

    if llm_degraded.active and settings.llm_provider.lower() == "gemini":
        if not _interactive(triggered_by):
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
        # Manual runs proceed — a real 429 during the call re-trips degraded mode.

    # Autonomous runs pause once only the interactive Flash reserve is left;
    if not _interactive(triggered_by) and settings.llm_provider.lower() == "gemini":
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
        Priority.INTERACTIVE if _interactive(triggered_by) else Priority.AUTONOMOUS
    )

    # Run admission lives in the kernel: interactive runs start immediately,
    # background runs share a bounded pool (kernel_background_run_limit).
    async with get_scheduler().run_slot():
        start = time.time()
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        set_thread_initiator(thread_id, triggered_by)

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
            **audit_payload(thread_id, triggered_by),
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
                    # Approval surfaces (dashboard modal, Obsidian plugin) need
                    # the draft without a live graph-state read.
                    payload={
                        "draft": state_values.get("draft", ""),
                        "confidence": state_values.get("confidence_score", 0.0),
                    },
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
                waiting_payload: dict[str, Any] = {
                    "type": "approval_required",
                    "thread_id": thread_id,
                    "skill": skill_name,
                    "draft": state_values.get("draft", ""),
                    "confidence": state_values.get("confidence_score", 0.0),
                    "status": "waiting_for_input",
                    **audit_payload(thread_id, triggered_by),
                }
                gated = last_gated_action(thread_id)
                if gated:
                    waiting_payload["gated_action"] = gated
                bus.publish(RUN_WAITING, waiting_payload, session_id=session_id, thread_id=thread_id)
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
                **audit_payload(thread_id, triggered_by),
            }, session_id=session_id, thread_id=thread_id)
            clear_run_context(thread_id)
            return {"status": "failed", "thread_id": thread_id, "error": str(e)}
