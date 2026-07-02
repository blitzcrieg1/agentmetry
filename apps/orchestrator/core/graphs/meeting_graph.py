from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.graphs.checkpointer import checkpointer
from core.graphs.node_events import emit_node
from core.llm.client import call_llm


class MeetingState(TypedDict):
    user_input: str
    system_context: str
    skill_config: dict[str, Any]
    messages: Annotated[list[BaseMessage], add_messages]
    raw_notes: str
    extracted: str
    summary: str
    cost: float
    input_tokens: int
    output_tokens: int
    context_sources: list[str]
    thread_id: str
    session_id: str


def _estimate_tokens(text: str) -> int:
    return len(text.split())


def _metrics(state: MeetingState) -> dict[str, Any]:
    return {
        "input_tokens": state.get("input_tokens", 0),
        "output_tokens": state.get("output_tokens", 0),
        "cost": state.get("cost", 0),
    }


async def ingest_node(state: MeetingState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    await emit_node(session_id, "ingest", "running")

    combined = f"{state['user_input']}\n\nVault context:\n{state['system_context']}"
    tokens_in = _estimate_tokens(combined)

    result = {
        "raw_notes": combined,
        "messages": [AIMessage(content=f"[Ingest] Loaded {len(combined)} chars of context")],
        "input_tokens": state.get("input_tokens", 0) + tokens_in,
    }
    await emit_node(session_id, "ingest", "completed", output="Context ingested", metrics=_metrics({**state, **result}))
    await emit_node(session_id, "extract", "running")
    return result


async def extract_node(state: MeetingState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    system = state["skill_config"].get("system_prompt", "")

    prompt = f"""Extract from these meeting notes:
- Key decisions
- Action items (with owners if mentioned)
- Open questions

Notes:
{state['raw_notes']}"""

    extracted = await call_llm(prompt, system, session_id=session_id, node="extract")
    tokens_in = _estimate_tokens(prompt + system)
    tokens_out = _estimate_tokens(extracted)

    result = {
        "extracted": extracted,
        "messages": [AIMessage(content=f"[Extract]\n{extracted}")],
        "input_tokens": state["input_tokens"] + tokens_in,
        "output_tokens": state.get("output_tokens", 0) + tokens_out,
        "cost": state.get("cost", 0) + (tokens_in * 0.000001 + tokens_out * 0.000003),
    }
    await emit_node(session_id, "extract", "completed", output=extracted, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "summarize", "running")
    return result


async def summarize_node(state: MeetingState) -> dict[str, Any]:
    session_id = state.get("session_id", "")

    prompt = f"""Write an executive meeting summary from this extraction.

Use markdown with sections: Executive Summary, Decisions, Action Items, Next Steps.

Extraction:
{state['extracted']}"""

    summary = await call_llm(prompt, session_id=session_id, node="summarize")
    tokens_in = _estimate_tokens(prompt)
    tokens_out = _estimate_tokens(summary)

    result = {
        "summary": summary,
        "messages": [AIMessage(content=f"[Summarize]\n{summary}")],
        "input_tokens": state["input_tokens"] + tokens_in,
        "output_tokens": state["output_tokens"] + tokens_out,
        "cost": state["cost"] + (tokens_in * 0.000001 + tokens_out * 0.000003),
    }
    await emit_node(session_id, "summarize", "completed", output=summary, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "finalize", "running")
    return result


async def finalize_node(state: MeetingState) -> dict[str, Any]:
    session_id = state.get("session_id", "")
    final = state["summary"]

    result = {
        "messages": [AIMessage(content=f"[Final Summary]\n{final}")],
    }
    await emit_node(session_id, "finalize", "completed", output=final, metrics=_metrics(state))
    return result


def build_meeting_graph() -> StateGraph:
    graph = StateGraph(MeetingState)

    graph.add_node("ingest", ingest_node)
    graph.add_node("extract", extract_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "extract")
    graph.add_edge("extract", "summarize")
    graph.add_edge("summarize", "finalize")
    graph.add_edge("finalize", END)

    return graph


meeting_graph = build_meeting_graph().compile(checkpointer=checkpointer)
