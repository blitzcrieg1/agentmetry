from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.graphs.node_events import emit_node
from core.graphs.usage_helpers import merge_llm_usage
from core.llm.client import call_llm


class WeeklyReviewState(TypedDict):
    user_input: str
    system_context: str
    skill_config: dict[str, Any]
    messages: Annotated[list[BaseMessage], add_messages]
    collected: str
    analysis: str
    priorities: str
    summary: str
    cost: float
    input_tokens: int
    output_tokens: int
    llm_providers: list[str]
    context_sources: list[str]
    thread_id: str
    session_id: str


def _metrics(state: WeeklyReviewState) -> dict[str, Any]:
    return {
        "input_tokens": state.get("input_tokens", 0),
        "output_tokens": state.get("output_tokens", 0),
        "cost": state.get("cost", 0),
    }


async def collect_node(state: WeeklyReviewState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    await emit_node(session_id, "collect", "running")

    combined = f"{state['user_input']}\n\nVault context:\n{state['system_context']}"
    result = {
        "collected": combined,
        "messages": [AIMessage(content=f"[Collect] Loaded {len(combined)} chars from vault")],
    }
    await emit_node(session_id, "collect", "completed", output="Context collected", metrics=_metrics({**state, **result}))
    await emit_node(session_id, "analyze", "running")
    return result


async def analyze_node(state: WeeklyReviewState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    system = state["skill_config"].get("system_prompt", "")

    prompt = f"""Analyze this week's vault activity and notes.

Identify:
- Completed work and wins
- Stalled items and blockers
- Patterns across inbox, active loops, and archive

Context:
{state['collected']}"""

    llm = await call_llm(prompt, system, session_id=session_id, node="analyze")

    result = {
        "analysis": llm.text,
        "messages": [AIMessage(content=f"[Analyze]\n{llm.text}")],
        **merge_llm_usage(state, llm),
    }
    await emit_node(session_id, "analyze", "completed", output=llm.text, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "prioritize", "running")
    return result


async def prioritize_node(state: WeeklyReviewState) -> dict[str, Any]:
    session_id = state.get("session_id", "")

    prompt = f"""From this analysis, produce a prioritized action list for next week.

Use markdown with: Top 3 Priorities, Quick Wins, Defer/Delegate, Open Loops to Close.

Analysis:
{state['analysis']}"""

    llm = await call_llm(prompt, session_id=session_id, node="prioritize")

    result = {
        "priorities": llm.text,
        "messages": [AIMessage(content=f"[Prioritize]\n{llm.text}")],
        **merge_llm_usage(state, llm),
    }
    await emit_node(session_id, "prioritize", "completed", output=llm.text, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "finalize", "running")
    return result


async def finalize_node(state: WeeklyReviewState) -> dict[str, Any]:
    session_id = state.get("session_id", "")

    prompt = f"""Write a concise weekly review executive summary combining analysis and priorities.

Analysis:
{state['analysis']}

Priorities:
{state['priorities']}"""

    llm = await call_llm(prompt, session_id=session_id, node="finalize")

    result = {
        "summary": llm.text,
        "messages": [AIMessage(content=f"[Weekly Review]\n{llm.text}")],
        **merge_llm_usage(state, llm),
    }
    await emit_node(session_id, "finalize", "completed", output=llm.text, metrics=_metrics({**state, **result}))
    return result


def build_weekly_review_graph() -> StateGraph:
    graph = StateGraph(WeeklyReviewState)

    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("prioritize", prioritize_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "prioritize")
    graph.add_edge("prioritize", "finalize")
    graph.add_edge("finalize", END)

    return graph


def compile_weekly_review_graph():
    from core.graphs.checkpointer import get_checkpointer

    return build_weekly_review_graph().compile(checkpointer=get_checkpointer())
