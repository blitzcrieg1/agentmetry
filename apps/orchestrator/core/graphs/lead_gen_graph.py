from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.config import settings
from core.graphs.checkpointer import checkpointer
from core.graphs.node_events import emit_node
from core.llm.client import call_llm


class LeadGenState(TypedDict):
    user_input: str
    system_context: str
    skill_config: dict[str, Any]
    messages: Annotated[list[BaseMessage], add_messages]
    plan: str
    research: str
    draft: str
    critique: str
    confidence_score: float
    requires_approval: bool
    approved: bool | None
    modified_input: str | None
    cost: float
    input_tokens: int
    output_tokens: int
    context_sources: list[str]
    key_decisions: list[str]
    thread_id: str
    session_id: str


def _estimate_tokens(text: str) -> int:
    return len(text.split())


async def planner_node(state: LeadGenState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    await emit_node(session_id, "planner", "running")

    system = state["skill_config"].get("system_prompt", "")
    context = state["system_context"]

    prompt = f"""You are the Planner agent. Break down this lead gen task into sub-steps.

User request: {state['user_input']}

Available context:
{context}

Output a numbered plan with: research targets, personalization angles, and email structure."""

    plan = await call_llm(prompt, system, session_id=session_id, node="planner")
    tokens_in = _estimate_tokens(prompt + system)
    tokens_out = _estimate_tokens(plan)

    result = {
        "plan": plan,
        "messages": [AIMessage(content=f"[Planner]\n{plan}")],
        "input_tokens": state.get("input_tokens", 0) + tokens_in,
        "output_tokens": state.get("output_tokens", 0) + tokens_out,
        "cost": state.get("cost", 0) + (tokens_in * 0.000001 + tokens_out * 0.000003),
    }
    await emit_node(session_id, "planner", "completed", output=plan, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "researcher", "running")
    return result


async def researcher_node(state: LeadGenState) -> dict[str, Any]:
    session_id = state.get("session_id", "")

    prompt = f"""You are the Researcher agent. Based on this plan, gather prospect intelligence.

Plan:
{state['plan']}

Context from vault:
{state['system_context']}

Identify top prospects, their recent news, and personalization hooks."""

    research = await call_llm(prompt, session_id=session_id, node="researcher")
    tokens_in = _estimate_tokens(prompt)
    tokens_out = _estimate_tokens(research)

    sources = [
        line.split("]")[0].replace("[Source: ", "")
        for line in state["system_context"].split("\n")
        if line.startswith("[Source:")
    ]

    result = {
        "research": research,
        "messages": [AIMessage(content=f"[Researcher]\n{research}")],
        "context_sources": sources[:5],
        "input_tokens": state["input_tokens"] + tokens_in,
        "output_tokens": state["output_tokens"] + tokens_out,
        "cost": state["cost"] + (tokens_in * 0.000001 + tokens_out * 0.000003),
    }
    await emit_node(session_id, "researcher", "completed", output=research, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "writer", "running")
    return result


async def writer_node(state: LeadGenState) -> dict[str, Any]:
    session_id = state.get("session_id", "")

    prompt = f"""You are the Writer agent. Draft a personalized outreach email.

Research:
{state['research']}

Brand context:
{state['system_context']}

Write a concise email (under 150 words) with subject line. Use technical peer tone."""

    draft = await call_llm(prompt, session_id=session_id, node="writer")
    tokens_in = _estimate_tokens(prompt)
    tokens_out = _estimate_tokens(draft)

    result = {
        "draft": draft,
        "messages": [AIMessage(content=f"[Writer]\n{draft}")],
        "input_tokens": state["input_tokens"] + tokens_in,
        "output_tokens": state["output_tokens"] + tokens_out,
        "cost": state["cost"] + (tokens_in * 0.000001 + tokens_out * 0.000003),
    }
    await emit_node(session_id, "writer", "completed", output=draft, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "critic", "running")
    return result


async def critic_node(state: LeadGenState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    threshold = state["skill_config"].get(
        "approval_threshold", settings.approval_threshold
    )

    prompt = f"""You are the Critic agent. Review this email draft against brand guidelines.

Draft:
{state.get('modified_input') or state['draft']}

Brand guidelines context:
{state['system_context']}

Rate confidence 0.0-1.0 and list any issues. Format:
CONFIDENCE: <score>
ISSUES: <list or "none">
DECISIONS: <key decisions made>"""

    critique = await call_llm(prompt, session_id=session_id, node="critic")
    tokens_in = _estimate_tokens(prompt)
    tokens_out = _estimate_tokens(critique)

    confidence = 0.85
    for line in critique.split("\n"):
        if line.startswith("CONFIDENCE:"):
            try:
                confidence = float(line.split(":")[1].strip())
            except ValueError:
                pass

    decisions = []
    capture = False
    for line in critique.split("\n"):
        if line.startswith("DECISIONS:"):
            capture = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                decisions.append(rest)
        elif capture and line.strip():
            decisions.append(line.strip())

    requires_approval = confidence < threshold

    result = {
        "critique": critique,
        "confidence_score": confidence,
        "requires_approval": requires_approval,
        "key_decisions": decisions,
        "messages": [AIMessage(content=f"[Critic]\n{critique}")],
        "input_tokens": state["input_tokens"] + tokens_in,
        "output_tokens": state["output_tokens"] + tokens_out,
        "cost": state["cost"] + (tokens_in * 0.000001 + tokens_out * 0.000003),
    }
    await emit_node(session_id, "critic", "completed", output=critique, metrics=_metrics({**state, **result}))
    return result


def _metrics(state: LeadGenState) -> dict[str, Any]:
    return {
        "input_tokens": state.get("input_tokens", 0),
        "output_tokens": state.get("output_tokens", 0),
        "cost": state.get("cost", 0),
    }


def should_request_approval(state: LeadGenState) -> str:
    if state.get("requires_approval") and state.get("approved") is None:
        return "human_approval"
    return "finalize"


async def human_approval_node(state: LeadGenState) -> dict[str, Any]:
    """Runs after graph resume — records approval and continues to finalize."""
    session_id = state.get("session_id", "")
    if state.get("approved"):
        await emit_node(session_id, "human_approval", "completed", output="Approved by human")
    else:
        await emit_node(session_id, "human_approval", "waiting", output=state.get("draft", ""))
    return {
        "messages": [
            AIMessage(
                content=f"[Approval Gate] Confidence {state['confidence_score']:.2f} "
                f"— {'approved' if state.get('approved') else 'waiting for human approval'}."
            )
        ],
    }


async def finalize_node(state: LeadGenState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    await emit_node(session_id, "finalize", "running")

    final = state.get("modified_input") or state["draft"]
    status = "approved" if state.get("approved") else "auto-approved"

    result = {
        "messages": [
            AIMessage(content=f"[Final Output — {status}]\n{final}")
        ],
    }
    await emit_node(session_id, "finalize", "completed", output=final, metrics=_metrics(state))
    return result


def build_lead_gen_graph() -> StateGraph:
    graph = StateGraph(LeadGenState)

    graph.add_node("planner", planner_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("writer", writer_node)
    graph.add_node("critic", critic_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", "critic")
    graph.add_conditional_edges("critic", should_request_approval)
    graph.add_edge("human_approval", "finalize")
    graph.add_edge("finalize", END)

    return graph


def compile_lead_gen_graph():
    return build_lead_gen_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approval"],
    )


lead_gen_graph = compile_lead_gen_graph()
