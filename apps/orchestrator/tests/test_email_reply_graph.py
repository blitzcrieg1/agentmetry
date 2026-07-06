"""Email reply graph — classify routing and SOP load replanning."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import core.graphs.email_reply_graph as email_module
from core.drivers.host import MCPHost
from core.drivers.spec import DriverSpec
from core.graphs.email_reply_graph import compile_email_reply_graph
from core.llm.types import LLMResult, LLMUsage

_FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def _skill(**overrides) -> dict:
    base = {
        "name": "email_demo",
        "graph": "email_reply",
        "tools": ["fake.*", "vault_fs.*"],
        "approval_threshold": 1.1,
        "nodes": ["fetch", "draft", "critic", "human_approval", "deliver", "finalize"],
        "tool_only_nodes": ["fetch", "load_client_sop", "load_generic_sop", "deliver"],
        "node_tools": {
            "fetch": [
                {"tool": "fake.echo", "args": {"text": "thread-body"}, "output": "thread_text"}
            ],
            "load_client_sop": [
                {
                    "tool": "fake.echo",
                    "args": {"text": "{client_note_path}"},
                    "output": "sop_text",
                }
            ],
            "load_generic_sop": [
                {"tool": "fake.echo", "args": {"text": "generic-sop"}, "output": "sop_text"}
            ],
            "deliver": [
                {"tool": "fake.echo", "args": {"text": "{approved_draft}"}, "output": "receipt"}
            ],
        },
        "node_prompts": {"draft": "Draft using SOP:\n{sop_text}\nThread:\n{thread_text}"},
    }
    base.update(overrides)
    return base


@pytest.fixture
async def wired(monkeypatch: pytest.MonkeyPatch):
    host = MCPHost()
    spec = DriverSpec(
        name="fake", transport="stdio", command=sys.executable, args=[str(_FIXTURE)]
    )
    assert await host.mount(spec)
    monkeypatch.setattr("core.graphs.pipeline_graph.get_mcp_host", lambda: host)

    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr("core.graphs.checkpointer.get_checkpointer", lambda: InMemorySaver())

    calls: list[str] = []

    async def fake_llm(state, prompt, *, system="", node=""):
        calls.append(node)
        if node == "classify_thread":
            text = (
                "ROUTE: client_known\n"
                "CLIENT_NOTE: 10-Knowledge/clients/acme.md\n"
                "REASON: matched domain"
            )
        elif node == "draft":
            text = "draft-from-sop"
        elif node == "critic":
            text = "CONFIDENCE: 0.5\nISSUES: none\nDECISIONS: used client sop"
        else:
            text = f"text-from-{node}"

        from core.graphs.usage_helpers import merge_llm_usage

        llm = LLMResult(text=text, provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr(email_module, "graph_call_llm", fake_llm)
    monkeypatch.setattr("core.graphs.pipeline_graph.graph_call_llm", fake_llm)

    yield calls
    await host.unmount_all()


def _state(skill: dict) -> dict:
    return {
        "user_input": "thread-abc",
        "system_context": "vault ctx",
        "skill_config": skill,
        "messages": [],
        "step_outputs": {},
        "cost": 0.0,
        "session_id": "s",
        "thread_id": "t-email",
    }


async def test_client_known_routes_through_client_sop_load(wired):
    calls = wired
    skill = _skill()
    graph = compile_email_reply_graph(skill)

    final = await graph.ainvoke(_state(skill), {"configurable": {"thread_id": "t-email"}})

    assert "classify_thread" in calls
    assert "draft" in calls
    assert final["step_outputs"]["sop_text"] == "10-Knowledge/clients/acme.md"[::-1]
    assert final["draft"] == "draft-from-sop"


async def test_client_unknown_uses_generic_sop(wired, monkeypatch: pytest.MonkeyPatch):
    async def classify_unknown(state, prompt, *, system="", node=""):
        from core.graphs.usage_helpers import merge_llm_usage

        text = "ROUTE: client_unknown\nCLIENT_NOTE: none\nREASON: new sender"
        llm = LLMResult(text=text, provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    async def fake_llm(state, prompt, *, system="", node=""):
        if node == "classify_thread":
            return await classify_unknown(state, prompt, system=system, node=node)
        from core.graphs.usage_helpers import merge_llm_usage

        if node == "draft":
            text = "generic draft"
        elif node == "critic":
            text = "CONFIDENCE: 0.5\nISSUES: none\nDECISIONS: generic"
        else:
            text = node
        llm = LLMResult(text=text, provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr(email_module, "graph_call_llm", fake_llm)
    monkeypatch.setattr("core.graphs.pipeline_graph.graph_call_llm", fake_llm)

    skill = _skill()
    graph = compile_email_reply_graph(skill)
    final = await graph.ainvoke(_state(skill), {"configurable": {"thread_id": "t2"}})

    assert final["step_outputs"]["sop_text"] == "generic-sop"[::-1]


async def test_thread_stale_replans_fetch_once(wired, monkeypatch: pytest.MonkeyPatch):
    classify_calls = {"n": 0}

    async def fake_llm(state, prompt, *, system="", node=""):
        from core.graphs.usage_helpers import merge_llm_usage

        if node == "classify_thread":
            classify_calls["n"] += 1
            if classify_calls["n"] == 1:
                text = "ROUTE: thread_stale\nCLIENT_NOTE: none\nREASON: truncated"
            else:
                text = "ROUTE: client_unknown\nCLIENT_NOTE: none\nREASON: ok now"
        elif node == "draft":
            text = "after replan"
        elif node == "critic":
            text = "CONFIDENCE: 0.5\nISSUES: none\nDECISIONS: replanned"
        else:
            text = node
        llm = LLMResult(text=text, provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr(email_module, "graph_call_llm", fake_llm)
    monkeypatch.setattr("core.graphs.pipeline_graph.graph_call_llm", fake_llm)

    skill = _skill()
    graph = compile_email_reply_graph(skill)
    final = await graph.ainvoke(_state(skill), {"configurable": {"thread_id": "t3"}})

    assert classify_calls["n"] == 2
    assert final["draft"] == "after replan"


async def test_escalation_skips_draft_llm(wired, monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_llm(state, prompt, *, system="", node=""):
        calls.append(node)
        from core.graphs.usage_helpers import merge_llm_usage

        if node == "classify_thread":
            text = "ROUTE: needs_escalation\nCLIENT_NOTE: none\nREASON: legal"
        elif node == "escalate_draft":
            text = "holding reply"
        elif node == "critic":
            text = "CONFIDENCE: 0.1\nISSUES: escalate\nDECISIONS: cautious"
        else:
            text = node
        llm = LLMResult(text=text, provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr(email_module, "graph_call_llm", fake_llm)
    monkeypatch.setattr("core.graphs.pipeline_graph.graph_call_llm", fake_llm)

    skill = _skill()
    graph = compile_email_reply_graph(skill)
    final = await graph.ainvoke(_state(skill), {"configurable": {"thread_id": "t4"}})

    assert "draft" not in calls
    assert "escalate_draft" in calls
    assert final["draft"] == "holding reply"


async def test_interrupts_at_approval_gate(wired):
    skill = _skill()
    graph = compile_email_reply_graph(skill)
    config = {"configurable": {"thread_id": "t5"}}

    await graph.ainvoke(_state(skill), config)
    snapshot = await graph.aget_state(config)

    assert snapshot.next and "human_approval" in snapshot.next
    assert snapshot.values.get("draft") == "draft-from-sop"
