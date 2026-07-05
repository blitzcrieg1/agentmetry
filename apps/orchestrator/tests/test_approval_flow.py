"""End-to-end approval flow — pause, approve, reject, recover — on the mock LLM."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import HTTPException

import api.routes.skills as skills_route
import core.execution.service as service
import core.graphs.checkpointer as checkpointer_module
import core.graphs.node_events as node_events_module
from api.routes.skills import (
    ApprovalRequest,
    BatchApprovalRequest,
    approve_skill,
    batch_approve,
)
from core.config import settings
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient
from core.telemetry.pending_store import PendingThreadStore
from core.telemetry.store import TelemetryStore


class FakeRAG:
    async def query(self, query_text, top_k=5, filter_metadata=None, path_prefix=None):
        return []

    async def summarize_context(self, chunks, max_tokens=500):
        return ""


SKILL_YAML = {
    "name": "lead_gen",
    "display_name": "Lead Gen",
    "description": "test skill",
    "graph": "lead_gen",
    # Mock critic output has no CONFIDENCE line → defaults to 0.85 < 0.9,
    # so every run pauses at the approval gate.
    "approval_threshold": 0.9,
    "nodes": ["planner", "researcher", "writer", "critic", "human_approval", "finalize"],
}


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "lead_gen.yaml").write_text(yaml.dump(SKILL_YAML), encoding="utf-8")

    monkeypatch.setattr(settings, "llm_provider", "mock")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(checkpointer_module, "_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        node_events_module, "node_events_path", lambda: tmp_path / "node-events.jsonl"
    )

    await init_checkpointer()

    obsidian = ObsidianClient(vault)
    registry = SkillRegistry(obsidian)
    registry.reload()
    db_url = f"sqlite:///{(tmp_path / 'telemetry.db').as_posix()}"
    telemetry = TelemetryStore(db_url)
    pending_store = PendingThreadStore(db_url)
    pending_threads: dict = {}

    # The service and the skills route both bind these singletons by name;
    # approval resolution itself lives in the service module only.
    for module in (service, skills_route):
        monkeypatch.setattr(module, "obsidian", obsidian)
        monkeypatch.setattr(module, "pending_threads", pending_threads)
        monkeypatch.setattr(module, "skill_registry", registry)
    monkeypatch.setattr(service, "pending_store", pending_store)
    monkeypatch.setattr(service, "telemetry", telemetry)
    monkeypatch.setattr(service, "rag", FakeRAG())
    monkeypatch.setattr(service, "log_run", lambda event: None)
    monkeypatch.setattr(service, "append_vault_run_log", lambda line: None)

    yield SimpleNamespace(
        vault=vault,
        pending_threads=pending_threads,
        pending_store=pending_store,
    )

    await shutdown_checkpointer()


async def test_low_confidence_run_pauses_for_approval(wired):
    result = await service.run_skill("lead_gen", "draft outreach", "sess-1")

    assert result["status"] == "waiting_for_input"
    thread_id = result["thread_id"]
    assert thread_id in wired.pending_threads
    assert wired.pending_store.get(thread_id) is not None

    loops = list((wired.vault / "20-Active-Loops").glob("*.md"))
    assert len(loops) == 1
    assert "awaiting_approval" in loops[0].read_text(encoding="utf-8")


async def test_approve_resumes_and_archives(wired):
    result = await service.run_skill("lead_gen", "draft outreach", "sess-2")
    thread_id = result["thread_id"]

    outcome = await approve_skill(ApprovalRequest(thread_id=thread_id, approved=True))

    assert outcome["status"] == "approved"
    assert thread_id not in wired.pending_threads
    assert wired.pending_store.get(thread_id) is None

    archives = list((wired.vault / "30-Archive").glob("*.md"))
    assert len(archives) == 1
    content = archives[0].read_text(encoding="utf-8")
    assert f"thread_id: {thread_id}" in content
    assert "mock-dry-run" in content  # provider provenance survives to the ledger


async def test_reject_terminates_and_writes_crash_report(wired):
    result = await service.run_skill("lead_gen", "draft outreach", "sess-3")
    thread_id = result["thread_id"]

    outcome = await approve_skill(ApprovalRequest(thread_id=thread_id, approved=False))

    assert outcome["status"] == "terminated"
    assert thread_id not in wired.pending_threads
    assert wired.pending_store.get(thread_id) is None
    crash_reports = list((wired.vault / "30-Archive").glob("*crash*"))
    assert len(crash_reports) == 1

    loops = list((wired.vault / "20-Active-Loops").glob("*.md"))
    assert "terminated" in loops[0].read_text(encoding="utf-8")


async def test_recover_pending_threads_after_restart(wired):
    result = await service.run_skill("lead_gen", "draft outreach", "sess-4")
    thread_id = result["thread_id"]

    # Simulate a restart: in-memory pending map is gone, SQLite row remains.
    wired.pending_threads.clear()

    recovered = await service.recover_pending_threads()
    assert recovered == 1
    assert thread_id in wired.pending_threads

    # And the recovered thread is still approvable.
    outcome = await approve_skill(ApprovalRequest(thread_id=thread_id, approved=True))
    assert outcome["status"] == "approved"


async def test_approve_unknown_thread_is_404(wired):
    with pytest.raises(HTTPException) as exc:
        await approve_skill(ApprovalRequest(thread_id="does-not-exist", approved=True))
    assert exc.value.status_code == 404


async def test_batch_approve_resolves_all(wired):
    t1 = (await service.run_skill("lead_gen", "a", "b1"))["thread_id"]
    t2 = (await service.run_skill("lead_gen", "b", "b1"))["thread_id"]

    out = await batch_approve(BatchApprovalRequest(thread_ids=[t1, t2], approved=True))

    assert out["requested"] == 2 and out["resolved"] == 2
    assert {r["status"] for r in out["results"]} == {"approved"}
    assert t1 not in wired.pending_threads and t2 not in wired.pending_threads
    assert len(list((wired.vault / "30-Archive").glob("*lead_gen*.md"))) == 2


async def test_batch_reject_terminates_all(wired):
    t1 = (await service.run_skill("lead_gen", "a", "b2"))["thread_id"]
    t2 = (await service.run_skill("lead_gen", "b", "b2"))["thread_id"]

    out = await batch_approve(BatchApprovalRequest(thread_ids=[t1, t2], approved=False))

    assert out["resolved"] == 2
    assert {r["status"] for r in out["results"]} == {"terminated"}
    assert not wired.pending_threads


async def test_batch_isolates_failures(wired):
    good = (await service.run_skill("lead_gen", "a", "b3"))["thread_id"]

    out = await batch_approve(
        BatchApprovalRequest(thread_ids=[good, "does-not-exist"], approved=True)
    )

    assert out["requested"] == 2 and out["resolved"] == 1
    by_thread = {r["thread_id"]: r for r in out["results"]}
    assert by_thread[good]["status"] == "approved"
    assert by_thread["does-not-exist"]["status"] == "error"
    # The valid thread still resolved despite the bad one in the same call.
    assert good not in wired.pending_threads
