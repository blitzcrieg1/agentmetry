"""Tests for pre-step cost budget and YAML pipeline compiler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.graphs.pipeline_graph import compile_pipeline_graph
from core.graphs.usage_helpers import assert_cost_budget, graph_call_llm, merge_llm_usage
from core.llm.errors import CostBudgetExceeded
from core.llm.types import LLMResult, LLMUsage


def _llm_result(cost: float) -> LLMResult:
    return LLMResult(
        text="ok",
        provider="mock",
        usage=LLMUsage(input_tokens=1, output_tokens=1, cost=cost),
    )


def test_assert_cost_budget_blocks_at_cap():
    state = {"skill_config": {"max_cost_per_run": 0.10}, "cost": 0.10}
    with pytest.raises(CostBudgetExceeded):
        assert_cost_budget(state)


def test_merge_records_overshoot_and_next_gate_blocks():
    # Merge never raises — the result was already paid for; the overshoot is
    # recorded truthfully and the next pre-step gate stops the run.
    state = {"skill_config": {"max_cost_per_run": 0.10}, "cost": 0.08}
    merged = merge_llm_usage(state, _llm_result(0.03))
    assert merged["cost"] == pytest.approx(0.11)
    with pytest.raises(CostBudgetExceeded):
        assert_cost_budget({**state, **merged})


async def test_graph_call_llm_blocks_before_next_step():
    state = {"skill_config": {"max_cost_per_run": 0.05}, "cost": 0.05, "session_id": "s1"}

    async def boom(*args, **kwargs):
        raise AssertionError("LLM should not be called")

    import core.graphs.usage_helpers as helpers

    original = helpers.call_llm
    helpers.call_llm = boom
    try:
        with pytest.raises(CostBudgetExceeded):
            await graph_call_llm(state, "prompt", node="writer")
    finally:
        helpers.call_llm = original


def test_compile_pipeline_graph_linear(monkeypatch: pytest.MonkeyPatch):
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr(
        "core.graphs.checkpointer.get_checkpointer",
        lambda: InMemorySaver(),
    )
    skill = {
        "name": "demo",
        "graph": "pipeline",
        "nodes": ["plan", "draft", "finalize"],
        "system_prompt": "test",
    }
    graph = compile_pipeline_graph(skill)
    assert graph is not None


def test_compile_pipeline_graph_archive_alias(monkeypatch: pytest.MonkeyPatch):
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr(
        "core.graphs.checkpointer.get_checkpointer",
        lambda: InMemorySaver(),
    )
    skill = {
        "name": "demo",
        "graph": "pipeline",
        "nodes": ["research", "draft", "human_approval", "archive"],
        "system_prompt": "test",
        "approval_threshold": 1.1,
    }
    graph = compile_pipeline_graph(skill)
    assert graph is not None


def test_registry_supports_pipeline_graph_type():
    from core.graphs.registry import SkillRegistry

    assert "pipeline" in SkillRegistry.available_graph_types()


def test_malformed_skill_yaml_does_not_brick_reload(tmp_path: Path):
    from core.graphs.registry import SkillRegistry
    from core.memory.obsidian_client import ObsidianClient

    skill_dir = tmp_path / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "broken.yaml").write_text("just a string, not a mapping", encoding="utf-8")
    (skill_dir / "empty_pipeline.yaml").write_text(
        "name: empty_pipeline\ngraph: pipeline\nnodes: []\n", encoding="utf-8"
    )

    registry = SkillRegistry(ObsidianClient(tmp_path))
    registry.reload()  # must not raise despite two bad definitions
    assert registry.list_registered() == []


async def test_pipeline_draft_follows_latest_step(monkeypatch: pytest.MonkeyPatch):
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr(
        "core.graphs.checkpointer.get_checkpointer",
        lambda: InMemorySaver(),
    )

    outputs = iter(["THE PLAN", "THE DRAFT"])

    async def fake_call(state, prompt, *, system="", node=""):
        text = next(outputs)
        llm = LLMResult(text=text, provider="mock", usage=LLMUsage(cost=0.0))
        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr("core.graphs.pipeline_graph.graph_call_llm", fake_call)
    monkeypatch.setattr(
        "core.graphs.pipeline_graph.emit_node", AsyncMock()
    )

    skill = {"name": "demo", "graph": "pipeline", "nodes": ["plan", "draft", "finalize"]}
    graph = compile_pipeline_graph(skill)
    final = await graph.ainvoke(
        {
            "user_input": "x",
            "system_context": "",
            "skill_config": skill,
            "messages": [],
            "step_outputs": {},
            "cost": 0.0,
            "session_id": "s",
            "thread_id": "t",
        },
        {"configurable": {"thread_id": "t"}},
    )
    # The step named "draft" must own the draft — not the plan step.
    assert final["draft"] == "THE DRAFT"
    assert final["output"] == "THE DRAFT"


async def test_run_skill_stops_mid_graph_on_budget(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import core.execution.service as service
    import core.graphs.checkpointer as checkpointer_module
    import core.graphs.node_events as node_events_module
    from core.config import settings
    from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
    from core.graphs.registry import SkillRegistry
    from core.memory.obsidian_client import ObsidianClient

    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "summarize_meeting.yaml").write_text(
        "name: summarize_meeting\ngraph: summarize_meeting\n"
        "max_cost_per_run: 0.05\nnodes: [ingest, extract, summarize, finalize]\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "llm_provider", "mock")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(checkpointer_module, "_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        node_events_module, "node_events_path", lambda: tmp_path / "node-events.jsonl"
    )

    calls = {"n": 0}

    async def expensive_call(state, prompt, *, system="", node=""):
        calls["n"] += 1
        llm = _llm_result(0.03)
        from core.graphs.usage_helpers import merge_llm_usage

        return llm, merge_llm_usage(state, llm)

    monkeypatch.setattr("core.graphs.meeting_graph.graph_call_llm", expensive_call)

    await init_checkpointer()
    obsidian = ObsidianClient(vault)
    registry = SkillRegistry(obsidian)
    registry.reload()
    monkeypatch.setattr(service, "obsidian", obsidian)
    monkeypatch.setattr(service, "skill_registry", registry)
    monkeypatch.setattr(service, "rag", SimpleNamespace(
        query=AsyncMock(return_value=[]),
        summarize_context=AsyncMock(return_value=""),
    ))
    monkeypatch.setattr(service, "log_run", lambda event: None)
    monkeypatch.setattr(service, "append_vault_run_log", lambda line: None)

    result = await service.run_skill("summarize_meeting", "notes", "sess-budget")

    await shutdown_checkpointer()
    assert result["status"] == "budget_exceeded"
    assert calls["n"] == 2
