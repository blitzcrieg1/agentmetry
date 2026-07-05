"""Pipeline tools hook: declarative step tool calls through the governed host."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import core.graphs.pipeline_graph as pipeline_module
from core.drivers.host import MCPHost
from core.drivers.permissions import ToolPermissionError
from core.drivers.spec import DriverSpec
from core.graphs.pipeline_graph import compile_pipeline_graph
from core.llm.types import LLMResult, LLMUsage

_FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def _skill(tools: list[str]) -> dict:
    return {
        "name": "tool_demo",
        "graph": "pipeline",
        "tools": tools,
        "nodes": ["summarize", "finalize"],
        "node_tools": {
            "summarize": [
                {"tool": "fake.echo", "args": {"text": "{user_input}"}, "output": "note_text"}
            ]
        },
        "node_prompts": {"summarize": "Summarize this:\n{note_text}"},
    }


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    host = MCPHost()
    spec = DriverSpec(
        name="fake", transport="stdio", command=sys.executable, args=[str(_FIXTURE)]
    )
    assert await host.mount(spec)
    monkeypatch.setattr(pipeline_module, "get_mcp_host", lambda: host)

    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr("core.graphs.checkpointer.get_checkpointer", lambda: InMemorySaver())

    prompts: list[str] = []

    async def fake_llm(state, prompt, *, system="", node=""):
        prompts.append(prompt)
        llm = LLMResult(text=f"summary-by-{node}", provider="mock", usage=LLMUsage(cost=0.0))
        from core.graphs.usage_helpers import merge_llm_usage

        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr(pipeline_module, "graph_call_llm", fake_llm)

    yield host, prompts
    await host.unmount_all()


def _initial_state(skill: dict) -> dict:
    return {
        "user_input": "blackbox",
        "system_context": "",
        "skill_config": skill,
        "messages": [],
        "step_outputs": {},
        "cost": 0.0,
        "session_id": "s",
        "thread_id": "t",
    }


async def test_step_tool_results_flow_into_prompt_and_state(wired):
    _, prompts = wired
    skill = _skill(tools=["vault_fs.*", "fake.*"])
    graph = compile_pipeline_graph(skill)

    final = await graph.ainvoke(_initial_state(skill), {"configurable": {"thread_id": "t"}})

    # The fixture reverses input: real stdio round-trip, injected by name.
    assert final["step_outputs"]["note_text"] == "xobkcalb"
    assert "Summarize this:\nxobkcalb" in prompts[0]
    assert final["draft"] == "summary-by-summarize"


async def test_step_tools_respect_skill_allowlist(wired):
    skill = _skill(tools=[])  # closed by default — node_tools alone grant nothing
    graph = compile_pipeline_graph(skill)

    with pytest.raises(ToolPermissionError):
        await graph.ainvoke(_initial_state(skill), {"configurable": {"thread_id": "t2"}})


async def test_tool_only_node_skips_llm_and_keeps_draft(wired):
    _, prompts = wired
    skill = {
        "name": "deliver_demo",
        "graph": "pipeline",
        "tools": ["fake.*"],
        "nodes": ["deliver", "finalize"],
        "tool_only_nodes": ["deliver"],
        "node_tools": {
            "deliver": [
                {"tool": "fake.echo", "args": {"text": "{approved_draft}"}, "output": "receipt"}
            ]
        },
    }
    graph = compile_pipeline_graph(skill)
    state = _initial_state(skill)
    state["draft"] = "approved text"

    final = await graph.ainvoke(state, {"configurable": {"thread_id": "t4"}})

    # Fixture echoes reversed: proof the tool received the approved draft.
    assert final["step_outputs"]["receipt"] == "approved text"[::-1]
    assert final["draft"] == "approved text"   # tool-only step never overwrites it
    assert prompts == []                        # and never calls the LLM


async def test_approved_draft_prefers_human_edit(wired):
    _, _ = wired
    skill = {
        "name": "deliver_edited",
        "graph": "pipeline",
        "tools": ["fake.*"],
        "nodes": ["deliver", "finalize"],
        "tool_only_nodes": ["deliver"],
        "node_tools": {
            "deliver": [
                {"tool": "fake.echo", "args": {"text": "{approved_draft}"}, "output": "receipt"}
            ]
        },
    }
    graph = compile_pipeline_graph(skill)
    state = _initial_state(skill)
    state["draft"] = "original"
    state["modified_input"] = "edited"

    final = await graph.ainvoke(state, {"configurable": {"thread_id": "t5"}})

    # The human's edit, not the pre-approval draft, reaches the tool.
    assert final["step_outputs"]["receipt"] == "edited"[::-1]


async def test_steps_without_tools_skip_the_host(monkeypatch: pytest.MonkeyPatch):
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr("core.graphs.checkpointer.get_checkpointer", lambda: InMemorySaver())

    def exploding_host():
        raise AssertionError("host must not be touched without node_tools")

    monkeypatch.setattr(pipeline_module, "get_mcp_host", exploding_host)

    async def fake_llm(state, prompt, *, system="", node=""):
        from core.graphs.usage_helpers import merge_llm_usage

        llm = LLMResult(text="ok", provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr(pipeline_module, "graph_call_llm", fake_llm)

    skill = {"name": "plain", "graph": "pipeline", "nodes": ["draft", "finalize"]}
    graph = compile_pipeline_graph(skill)
    final = await graph.ainvoke(_initial_state(skill), {"configurable": {"thread_id": "t3"}})
    assert final["draft"] == "ok"
