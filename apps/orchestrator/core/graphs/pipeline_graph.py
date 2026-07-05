"""YAML pipeline compiler — build LangGraph skills from vault node lists."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.config import settings
from core.drivers.host import get_mcp_host
from core.graphs.node_events import emit_node
from core.graphs.usage_helpers import graph_call_llm

_RESERVED = frozenset({"critic", "human_approval", "finalize"})


def _tool_result_text(result: Any) -> str:
    """Flatten an MCP CallToolResult into plain text for prompt injection."""
    parts = [getattr(item, "text", "") for item in getattr(result, "content", [])]
    return "\n".join(p for p in parts if p)


async def _run_step_tools(state: "PipelineState", step_id: str) -> dict[str, str]:
    """Execute a step's declarative tool calls; results become step outputs.

    YAML shape:
        node_tools:
          summarize:
            - tool: vault_fs.read_note
              args: {path: "{user_input}"}
              output: note_text

    Args are templated from user_input and prior step outputs. Every call goes
    through the governed host path (per-skill allowlist, Tier 0 exec gate).
    """
    calls = (state["skill_config"].get("node_tools") or {}).get(step_id) or []
    if not calls:
        return {}

    outputs = dict(state.get("step_outputs") or {})
    # Post-approval steps must deliver what the human approved (edits included),
    # not the pre-approval draft — expose it to arg templating as {approved_draft}.
    outputs.setdefault(
        "approved_draft", state.get("modified_input") or state.get("draft") or ""
    )
    host = get_mcp_host()
    results: dict[str, str] = {}
    for call in calls:
        qualified = call["tool"]
        raw_args = call.get("args") or {}
        args = {
            key: value.format(user_input=state["user_input"], **outputs)
            if isinstance(value, str)
            else value
            for key, value in raw_args.items()
        }
        result = await host.call_tool(
            qualified,
            args,
            skill_config=state["skill_config"],
            session_id=state.get("session_id", ""),
            thread_id=state.get("thread_id", ""),
        )
        key = call.get("output") or qualified.replace(".", "_")
        text = _tool_result_text(result)
        results[key] = text
        outputs[key] = text
    return results


class PipelineState(TypedDict):
    user_input: str
    system_context: str
    skill_config: dict[str, Any]
    messages: Annotated[list[BaseMessage], add_messages]
    step_outputs: dict[str, str]
    draft: str
    output: str
    critique: str
    confidence_score: float
    requires_approval: bool
    approved: bool | None
    modified_input: str | None
    cost: float
    input_tokens: int
    output_tokens: int
    llm_providers: list[str]
    context_sources: list[str]
    key_decisions: list[str]
    thread_id: str
    session_id: str


def _metrics(state: PipelineState) -> dict[str, Any]:
    return {
        "input_tokens": state.get("input_tokens", 0),
        "output_tokens": state.get("output_tokens", 0),
        "cost": state.get("cost", 0),
    }


def _format_prior_steps(step_outputs: dict[str, str]) -> str:
    if not step_outputs:
        return "(none yet)"
    return "\n\n".join(f"### {name}\n{text}" for name, text in step_outputs.items())


def _default_step_prompt(state: PipelineState, step_id: str) -> str:
    title = step_id.replace("_", " ").title()
    return f"""You are the {title} agent.

User request:
{state['user_input']}

Vault context:
{state['system_context']}

Prior steps:
{_format_prior_steps(state.get('step_outputs') or {})}

Complete your part of the pipeline and output only your step result."""


def _resolve_prompt(state: PipelineState, step_id: str) -> str:
    prompts = state["skill_config"].get("node_prompts") or {}
    template = prompts.get(step_id)
    if template:
        return template.format(
            user_input=state["user_input"],
            system_context=state["system_context"],
            prior_steps=_format_prior_steps(state.get("step_outputs") or {}),
            **(state.get("step_outputs") or {}),
        )
    return _default_step_prompt(state, step_id)


def _make_step_node(step_id: str):
    async def step_node(state: PipelineState) -> dict[str, Any]:
        session_id = state.get("session_id", "")
        thread_id = state.get("thread_id", "")
        await emit_node(session_id, thread_id, step_id, "running")

        outputs = dict(state.get("step_outputs") or {})
        tool_outputs = await _run_step_tools(state, step_id)
        outputs.update(tool_outputs)

        # Tool-only steps (e.g. a post-approval "deliver" that files a Gmail
        # draft) run their tools and stop: no LLM call, and crucially no
        # overwrite of `draft` — the approved text must survive to finalize.
        if step_id in (state["skill_config"].get("tool_only_nodes") or []):
            text = "\n\n".join(
                f"### {k}\n{v}" for k, v in tool_outputs.items()
            ) or "(no tool output)"
            result = {
                "step_outputs": outputs,
                "messages": [AIMessage(content=f"[{step_id}]\n{text}")],
            }
            await emit_node(
                session_id, thread_id, step_id, "completed",
                output=text, metrics=_metrics(state),
            )
            return result

        system = state["skill_config"].get("system_prompt", "")
        prompt = _resolve_prompt({**state, "step_outputs": outputs}, step_id)
        llm, usage = await graph_call_llm(state, prompt, system=system, node=step_id)

        outputs[step_id] = llm.text
        result: dict[str, Any] = {
            "step_outputs": outputs,
            "messages": [AIMessage(content=f"[{step_id}]\n{llm.text}")],
            **usage,
        }
        # Latest step wins: the critic reviews and finalize archives the most
        # recent content, not whatever step happened to run first.
        result["draft"] = llm.text
        await emit_node(
            session_id,
            thread_id,
            step_id,
            "completed",
            output=llm.text,
            metrics=_metrics({**state, **result}),
        )
        return result

    step_node.__name__ = f"{step_id}_node"
    return step_node


async def critic_node(state: PipelineState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    thread_id = state.get("thread_id", "")
    threshold = state["skill_config"].get("approval_threshold", settings.approval_threshold)
    await emit_node(session_id, thread_id, "critic", "running")

    draft = state.get("modified_input") or state.get("draft") or _format_prior_steps(state.get("step_outputs") or {})
    prompt = (state["skill_config"].get("node_prompts") or {}).get("critic") or f"""Review this output against brand guidelines.

Draft:
{draft}

Brand context:
{state['system_context']}

Rate confidence 0.0-1.0 and list any issues. Format:
CONFIDENCE: <score>
ISSUES: <list or "none">
DECISIONS: <key decisions made>"""

    llm, usage = await graph_call_llm(state, prompt, node="critic")

    confidence = 0.85
    for line in llm.text.split("\n"):
        if line.startswith("CONFIDENCE:"):
            try:
                confidence = float(line.split(":")[1].strip())
            except ValueError:
                pass

    decisions: list[str] = []
    capture = False
    for line in llm.text.split("\n"):
        if line.startswith("DECISIONS:"):
            capture = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                decisions.append(rest)
        elif capture and line.strip():
            decisions.append(line.strip())

    result = {
        "critique": llm.text,
        "confidence_score": confidence,
        "requires_approval": confidence < threshold,
        "key_decisions": decisions,
        "messages": [AIMessage(content=f"[Critic]\n{llm.text}")],
        **usage,
    }
    await emit_node(session_id, thread_id, "critic", "completed", output=llm.text, metrics=_metrics({**state, **result}))
    return result


async def human_approval_node(state: PipelineState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    thread_id = state.get("thread_id", "")
    if state.get("approved"):
        await emit_node(session_id, thread_id, "human_approval", "completed", output="Approved by human")
    else:
        await emit_node(session_id, thread_id, "human_approval", "waiting", output=state.get("draft", ""))
    return {
        "messages": [
            AIMessage(
                content=f"[Approval Gate] Confidence {state.get('confidence_score', 0):.2f} "
                f"— {'approved' if state.get('approved') else 'waiting for human approval'}."
            )
        ],
    }


async def finalize_node(state: PipelineState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    thread_id = state.get("thread_id", "")
    await emit_node(session_id, thread_id, "finalize", "running")

    final = state.get("modified_input") or state.get("draft") or state.get("output") or ""
    if not final and state.get("step_outputs"):
        last_key = list(state["step_outputs"].keys())[-1]
        final = state["step_outputs"][last_key]

    status = "approved" if state.get("approved") else "auto-approved"
    result = {
        "output": final,
        "messages": [AIMessage(content=f"[Final Output — {status}]\n{final}")],
    }
    await emit_node(session_id, thread_id, "finalize", "completed", output=final, metrics=_metrics(state))
    return result


def _should_request_approval(state: PipelineState) -> str:
    if state.get("requires_approval") and state.get("approved") is None:
        return "human_approval"
    return "finalize"


def compile_pipeline_graph(skill_config: dict[str, Any]):
    """Compile a linear YAML-defined pipeline into a checkpointed LangGraph."""
    node_names: list[str] = list(skill_config.get("nodes") or [])
    if not node_names:
        raise ValueError(f"Pipeline skill '{skill_config.get('name')}' has no nodes")

    graph = StateGraph(PipelineState)
    llm_steps = [name for name in node_names if name not in _RESERVED]
    has_critic = "critic" in node_names
    has_approval = "human_approval" in node_names
    has_finalize = "finalize" in node_names

    for step_id in llm_steps:
        graph.add_node(step_id, _make_step_node(step_id))
    if has_critic:
        graph.add_node("critic", critic_node)
    if has_approval:
        graph.add_node("human_approval", human_approval_node)
    if has_finalize:
        graph.add_node("finalize", finalize_node)

    ordered: list[str] = []
    for name in node_names:
        if name in _RESERVED:
            if name == "critic" and has_critic:
                ordered.append("critic")
            elif name == "human_approval" and has_approval:
                ordered.append("human_approval")
            elif name == "finalize" and has_finalize:
                ordered.append("finalize")
        else:
            ordered.append(name)

    graph.set_entry_point(ordered[0])
    for left, right in zip(ordered, ordered[1:]):
        if left == "critic" and has_approval:
            graph.add_conditional_edges(
                "critic",
                _should_request_approval,
                {
                    "human_approval": "human_approval",
                    # Without a finalize node, high confidence ends the run.
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
