from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from core.graphs.node_events import emit_node
from core.graphs.usage_helpers import merge_llm_usage
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
    llm_providers: list[str]
    context_sources: list[str]
    thread_id: str
    session_id: str


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

    result = {
        "raw_notes": combined,
        "messages": [AIMessage(content=f"[Ingest] Loaded {len(combined)} chars of context")],
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

    llm = await call_llm(prompt, system, session_id=session_id, node="extract")

    result = {
        "extracted": llm.text,
        "messages": [AIMessage(content=f"[Extract]\n{llm.text}")],
        **merge_llm_usage(state, llm),
    }
    await emit_node(session_id, "extract", "completed", output=llm.text, metrics=_metrics({**state, **result}))
    await emit_node(session_id, "summarize", "running")
    return result


async def summarize_node(state: MeetingState) -> dict[str, Any]:
    session_id = state.get("session_id", "")

    prompt = f"""Write an executive meeting summary from this extraction.

Use markdown with sections: Executive Summary, Decisions, Action Items, Next Steps.

Extraction:
{state['extracted']}"""

    llm = await call_llm(prompt, session_id=session_id, node="summarize")

    result = {
        "summary": llm.text,
        "messages": [AIMessage(content=f"[Summarize]\n{llm.text}")],
        **merge_llm_usage(state, llm),
    }
    await emit_node(session_id, "summarize", "completed", output=llm.text, metrics=_metrics({**state, **result}))
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


def compile_meeting_graph():
    from core.graphs.checkpointer import get_checkpointer

    return build_meeting_graph().compile(checkpointer=get_checkpointer())
