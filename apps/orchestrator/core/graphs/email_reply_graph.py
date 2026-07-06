"""Email reply compiler — governed pipeline with classify + SOP replanning."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph

from core.graphs.node_events import emit_node
from core.graphs.pipeline_graph import (
    _RESERVED,
    _make_step_node,
    _metrics,
    _should_request_approval,
    critic_node,
    finalize_node,
    human_approval_node,
)
from core.graphs.pipeline_graph import PipelineState
from core.graphs.usage_helpers import graph_call_llm


def _parse_classify(text: str) -> dict[str, str]:
    route = "client_unknown"
    client_note = ""
    for line in text.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("ROUTE:"):
            route = stripped.split(":", 1)[1].strip().lower().replace(" ", "_")
        elif upper.startswith("CLIENT_NOTE:"):
            val = stripped.split(":", 1)[1].strip()
            if val.lower() not in ("none", "n/a", ""):
                client_note = val
    return {"route": route, "client_note_path": client_note}


def _default_classify_prompt(state: PipelineState) -> str:
    thread = (state.get("step_outputs") or {}).get("thread_text", "")
    return f"""Classify this Gmail thread for reply routing.

Thread:
{thread}

Vault context (may include client notes):
{state.get("system_context", "")}

Output exactly these lines:
ROUTE: client_known | client_unknown | thread_stale | needs_escalation
CLIENT_NOTE: vault-relative path under 10-Knowledge/clients/ or none
REASON: one line

Use client_known only when a client note path is identifiable.
Use thread_stale only if the thread looks truncated or inconsistent.
Use needs_escalation for legal, pricing, or angry threads."""


def _default_escalate_prompt(state: PipelineState) -> str:
    thread = (state.get("step_outputs") or {}).get("thread_text", "")
    return f"""Draft a cautious holding reply — acknowledge, flag that you will confirm
internally, no factual claims, no pricing, under 80 words. Output body only.

Thread:
{thread}"""


def _make_classify_node(skill_config: dict[str, Any]):
    async def classify_thread_node(state: PipelineState) -> dict[str, Any]:
        session_id = state.get("session_id", "")
        thread_id = state.get("thread_id", "")
        await emit_node(session_id, thread_id, "classify_thread", "running")

        prompts = skill_config.get("node_prompts") or {}
        template = prompts.get("classify_thread")
        if template:
            prompt = template.format(
                user_input=state["user_input"],
                system_context=state.get("system_context", ""),
                **(state.get("step_outputs") or {}),
            )
        else:
            prompt = _default_classify_prompt(state)

        system = skill_config.get("system_prompt", "")
        llm, usage = await graph_call_llm(state, prompt, system=system, node="classify_thread")

        parsed = _parse_classify(llm.text)
        outputs = dict(state.get("step_outputs") or {})
        outputs["classify_thread"] = llm.text
        if parsed["client_note_path"]:
            outputs["client_note_path"] = parsed["client_note_path"]

        result: dict[str, Any] = {
            "step_outputs": outputs,
            "route": parsed["route"],
            "client_note_path": parsed["client_note_path"],
            "replan_count": state.get("replan_count", 0),
            "messages": [AIMessage(content=f"[classify_thread]\n{llm.text}")],
            **usage,
        }
        await emit_node(
            session_id,
            thread_id,
            "classify_thread",
            "completed",
            output=llm.text,
            metrics=_metrics({**state, **result}),
        )
        return result

    return classify_thread_node


def _make_escalate_node(skill_config: dict[str, Any]):
    async def escalate_draft_node(state: PipelineState) -> dict[str, Any]:
        session_id = state.get("session_id", "")
        thread_id = state.get("thread_id", "")
        await emit_node(session_id, thread_id, "escalate_draft", "running")

        prompts = skill_config.get("node_prompts") or {}
        template = prompts.get("escalate_draft")
        if template:
            prompt = template.format(
                user_input=state["user_input"],
                system_context=state.get("system_context", ""),
                **(state.get("step_outputs") or {}),
            )
        else:
            prompt = _default_escalate_prompt(state)

        system = skill_config.get("system_prompt", "")
        llm, usage = await graph_call_llm(state, prompt, system=system, node="escalate_draft")

        outputs = dict(state.get("step_outputs") or {})
        outputs["escalate_draft"] = llm.text

        result: dict[str, Any] = {
            "step_outputs": outputs,
            "draft": llm.text,
            "confidence_score": 0.0,
            "requires_approval": True,
            "messages": [AIMessage(content=f"[escalate_draft]\n{llm.text}")],
            **usage,
        }
        await emit_node(
            session_id,
            thread_id,
            "escalate_draft",
            "completed",
            output=llm.text,
            metrics=_metrics({**state, **result}),
        )
        return result

    return escalate_draft_node


async def replan_fetch_node(state: PipelineState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    thread_id = state.get("thread_id", "")
    count = state.get("replan_count", 0) + 1
    await emit_node(session_id, thread_id, "replan_fetch", "completed", output=f"replan #{count}")
    return {"replan_count": count}


def _route_after_classify(state: PipelineState) -> str:
    outputs = state.get("step_outputs") or {}
    parsed = _parse_classify(outputs.get("classify_thread", ""))
    route = parsed.get("route") or state.get("route") or "client_unknown"
    max_replan = int(state["skill_config"].get("max_replan_count", 1))
    replan = int(state.get("replan_count") or 0)

    if route == "thread_stale":
        return "replan_fetch" if replan < max_replan else "escalate_draft"
    if route == "needs_escalation":
        return "escalate_draft"
    if route == "client_known" and (parsed.get("client_note_path") or state.get("client_note_path")):
        return "load_client_sop"
    return "load_generic_sop"


def compile_email_reply_graph(skill_config: dict[str, Any]):
    """Compile customer_reply-style skills with classify + SOP load routing."""
    node_names: list[str] = list(skill_config.get("nodes") or [])
    if not node_names:
        raise ValueError(f"Email reply skill '{skill_config.get('name')}' has no nodes")

    fetch_step = node_names[0]
    if "draft" not in node_names:
        raise ValueError(
            f"Email reply skill '{skill_config.get('name')}' must include a draft node"
        )
    draft_idx = node_names.index("draft")
    if draft_idx == 0:
        raise ValueError(
            f"Email reply skill '{skill_config.get('name')}' must list fetch before draft"
        )

    suffix = node_names[draft_idx:]  # draft → … → finalize
    llm_steps = [n for n in node_names if n not in _RESERVED]

    has_critic = "critic" in node_names
    has_approval = "human_approval" in node_names
    has_finalize = "finalize" in node_names

    graph = StateGraph(PipelineState)

    graph.add_node("classify_thread", _make_classify_node(skill_config))
    graph.add_node("load_client_sop", _make_step_node("load_client_sop"))
    graph.add_node("load_generic_sop", _make_step_node("load_generic_sop"))
    graph.add_node("replan_fetch", replan_fetch_node)
    graph.add_node("escalate_draft", _make_escalate_node(skill_config))

    for step_id in llm_steps:
        graph.add_node(step_id, _make_step_node(step_id))
    if has_critic:
        graph.add_node("critic", critic_node)
    if has_approval:
        graph.add_node("human_approval", human_approval_node)
    if has_finalize:
        graph.add_node("finalize", finalize_node)

    graph.set_entry_point(fetch_step)
    graph.add_edge(fetch_step, "classify_thread")
    graph.add_conditional_edges(
        "classify_thread",
        _route_after_classify,
        {
            "load_client_sop": "load_client_sop",
            "load_generic_sop": "load_generic_sop",
            "escalate_draft": "escalate_draft",
            "replan_fetch": "replan_fetch",
        },
    )
    graph.add_edge("replan_fetch", fetch_step)
    graph.add_edge("load_client_sop", "draft")
    graph.add_edge("load_generic_sop", "draft")
    if has_critic:
        graph.add_edge("escalate_draft", "critic")
    elif has_finalize:
        graph.add_edge("escalate_draft", "finalize")
    else:
        graph.add_edge("escalate_draft", END)

    ordered: list[str] = []
    for name in suffix:
        if name in _RESERVED:
            if name == "critic" and has_critic:
                ordered.append("critic")
            elif name == "human_approval" and has_approval:
                ordered.append("human_approval")
            elif name == "finalize" and has_finalize:
                ordered.append("finalize")
        else:
            ordered.append(name)

    for left, right in zip(ordered, ordered[1:]):
        if left == "critic" and has_approval:
            graph.add_conditional_edges(
                "critic",
                _should_request_approval,
                {
                    "human_approval": "human_approval",
                    "finalize": "finalize" if has_finalize else END,
                },
            )
        else:
            graph.add_edge(left, right)

    last = ordered[-1]
    if last == "critic" and has_approval:
        pass
    elif last == "human_approval":
        if not has_finalize:
            graph.add_edge("human_approval", END)
    elif last != "finalize":
        graph.add_edge(last, END)
    elif has_finalize:
        graph.add_edge("finalize", END)

    from core.graphs.checkpointer import get_checkpointer

    kwargs: dict[str, Any] = {"checkpointer": get_checkpointer()}
    if has_approval:
        kwargs["interrupt_before"] = ["human_approval"]
    return graph.compile(**kwargs)
