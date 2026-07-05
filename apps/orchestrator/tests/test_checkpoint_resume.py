"""Crash-resume: orphaned runs re-enter their LangGraph checkpoint, never restart."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from core.execution.recovery import resume_orphan
from core.memory.obsidian_client import ObsidianClient


class FakeSnapshot(SimpleNamespace):
    pass


class FakeGraph:
    """Scripted graph: sequential aget_state snapshots + recorded ainvoke calls."""

    def __init__(self, snapshots: list[FakeSnapshot], invoke_result: dict | None = None):
        self._snapshots = list(snapshots)
        self.invoke_calls: list[Any] = []
        self._invoke_result = invoke_result or {}

    async def aget_state(self, config):
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]

    async def ainvoke(self, input_state, config):
        self.invoke_calls.append(input_state)
        return self._invoke_result


class FakeRegistry:
    def __init__(self, graph):
        self._graph = graph

    def get(self, skill_name):
        return self._graph


class FakeStore:
    def __init__(self):
        self.saved: list[dict] = []

    def save(self, thread_id, **kwargs):
        self.saved.append({"thread_id": thread_id, **kwargs})


class FakeScheduler:
    def run_slot(self):
        class _Slot:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        return _Slot()


@pytest.fixture
def vault(tmp_path) -> ObsidianClient:
    return ObsidianClient(tmp_path)


@pytest.fixture
def quiet_kernel(monkeypatch: pytest.MonkeyPatch):
    """Stub the scheduler, degraded flag, and finalize bookkeeping."""
    monkeypatch.setattr("core.kernel.scheduler.get_scheduler", lambda: FakeScheduler())
    monkeypatch.setattr("core.llm.degraded.llm_degraded", SimpleNamespace(active=False))

    finalized: list[dict] = []

    async def fake_finalize(**kwargs):
        finalized.append(kwargs)
        return {"status": kwargs.get("status_label", "completed"), "thread_id": kwargs["thread_id"]}

    monkeypatch.setattr("core.execution.service._finalize_execution", fake_finalize)
    return finalized


def _orphan(vault: ObsidianClient, thread_id: str = "abc12345-0000") -> str:
    path = vault.write_active_loop(thread_id, "demo_skill", "some input", nodes=["one", "two"])
    return path.relative_to(vault.vault_path).as_posix()


def _note_status(vault: ObsidianClient, rel_path: str) -> str:
    meta, _ = vault.parse_frontmatter(vault.read_note(rel_path) or "")
    return str(meta.get("status"))


async def test_resume_completes_mid_run_orphan_without_replaying_input(vault, quiet_kernel):
    rel = _orphan(vault)
    graph = FakeGraph(
        snapshots=[
            FakeSnapshot(values={"draft": "partial", "cost": 0.01}, next=("two",)),
            FakeSnapshot(values={"draft": "done", "cost": 0.02}, next=()),
        ],
        invoke_result={"draft": "done"},
    )

    result = await resume_orphan(
        rel, client=vault, registry=FakeRegistry(graph), pending={}, store=FakeStore()
    )

    assert result["status"] == "resumed_completed"
    # THE invariant: resume passes None, never the original state.
    assert graph.invoke_calls == [None]
    assert len(quiet_kernel) == 1
    assert quiet_kernel[0]["skill_name"] == "demo_skill"


async def test_resume_at_approval_gate_reregisters_pending(vault, quiet_kernel):
    rel = _orphan(vault, thread_id="gate1234-0000")
    graph = FakeGraph(
        snapshots=[FakeSnapshot(values={"draft": "hello", "confidence_score": 0.4},
                                next=("human_approval",))],
    )
    store = FakeStore()
    pending: dict[str, Any] = {}

    result = await resume_orphan(
        rel, client=vault, registry=FakeRegistry(graph), pending=pending, store=store
    )

    assert result["status"] == "resumed_waiting"
    assert graph.invoke_calls == []            # nothing re-ran
    assert "gate1234-0000" in pending
    assert store.saved and store.saved[0]["payload"]["draft"] == "hello"
    assert _note_status(vault, rel) == "awaiting_approval"
    assert quiet_kernel == []


async def test_resume_without_checkpoint_marks_failed(vault, quiet_kernel):
    rel = _orphan(vault, thread_id="none1234-0000")
    graph = FakeGraph(snapshots=[FakeSnapshot(values={}, next=())])

    result = await resume_orphan(
        rel, client=vault, registry=FakeRegistry(graph), pending={}, store=FakeStore()
    )

    assert result["status"] == "unresumable"
    assert _note_status(vault, rel) == "failed"


async def test_finished_graph_only_replays_bookkeeping(vault, quiet_kernel):
    rel = _orphan(vault, thread_id="fini1234-0000")
    graph = FakeGraph(
        snapshots=[FakeSnapshot(values={"draft": "all done", "cost": 0.03}, next=())],
    )

    result = await resume_orphan(
        rel, client=vault, registry=FakeRegistry(graph), pending={}, store=FakeStore()
    )

    assert result["status"] == "resumed_completed"
    assert graph.invoke_calls == []            # graph was already terminal
    assert len(quiet_kernel) == 1


async def test_healthy_approval_is_not_resumable(vault, quiet_kernel):
    thread_id = "live1234-0000"
    path = vault.write_active_loop(thread_id, "demo_skill", "x")
    rel = path.relative_to(vault.vault_path).as_posix()
    vault.resolve_active_loop(rel, "awaiting_approval")

    result = await resume_orphan(
        rel,
        client=vault,
        registry=FakeRegistry(FakeGraph(snapshots=[FakeSnapshot(values={}, next=())])),
        pending={thread_id: {"config": {}}},   # thread still live -> healthy
        store=FakeStore(),
    )

    assert result["status"] == "unresumable"


async def test_resume_failure_marks_note_failed(vault, quiet_kernel):
    rel = _orphan(vault, thread_id="boom1234-0000")

    class ExplodingGraph(FakeGraph):
        async def ainvoke(self, input_state, config):
            self.invoke_calls.append(input_state)
            raise RuntimeError("mid-resume crash")

    graph = ExplodingGraph(
        snapshots=[FakeSnapshot(values={"draft": "partial"}, next=("two",))],
    )

    result = await resume_orphan(
        rel, client=vault, registry=FakeRegistry(graph), pending={}, store=FakeStore()
    )

    assert result["status"] == "failed"
    assert "mid-resume crash" in result["error"]
    assert _note_status(vault, rel) == "failed"
