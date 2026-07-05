"""Channel router E2E — /skill, approve/reject, inbox filing — on the mock LLM.

Channels are just another ingress: the same run_skill / resolve_approval /
pending-store path as the dashboard, so this exercises the real graphs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import core.channels.router as router
import core.execution.service as service
from core.channels.base import InboundMessage
from core.config import settings
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.graphs.registry import SkillRegistry
from core.kernel.interrupts import InterruptVectorTable
from core.memory.obsidian_client import ObsidianClient
from core.telemetry.pending_store import PendingThreadStore
from core.telemetry.store import TelemetryStore

import core.graphs.checkpointer as checkpointer_module
import core.graphs.node_events as node_events_module


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
    # Mock critic yields confidence 0.85 < 0.9 → every run pauses at the gate.
    "approval_threshold": 0.9,
    "nodes": ["planner", "researcher", "writer", "critic", "human_approval", "finalize"],
}


def _msg(text: str) -> InboundMessage:
    return InboundMessage(channel="telegram", sender_id="424242", text=text)


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "lead_gen.yaml").write_text(yaml.dump(SKILL_YAML), encoding="utf-8")

    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "vault_path", vault)
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
    interrupt_table = InterruptVectorTable(db_url)
    pending_threads: dict = {}

    monkeypatch.setattr(service, "obsidian", obsidian)
    monkeypatch.setattr(service, "pending_store", pending_store)
    monkeypatch.setattr(service, "pending_threads", pending_threads)
    monkeypatch.setattr(service, "skill_registry", registry)
    monkeypatch.setattr(service, "telemetry", telemetry)
    monkeypatch.setattr(service, "rag", FakeRAG())
    monkeypatch.setattr(service, "log_run", lambda event: None)
    monkeypatch.setattr(service, "append_vault_run_log", lambda line: None)
    monkeypatch.setattr(service, "notify", lambda *a, **k: None)

    monkeypatch.setattr(router, "pending_threads", pending_threads)
    monkeypatch.setattr(router, "pending_store", pending_store)
    monkeypatch.setattr(router, "interrupt_table", interrupt_table)
    monkeypatch.setattr(router, "skill_registry", registry)
    monkeypatch.setattr(router, "telemetry", telemetry)

    yield SimpleNamespace(vault=vault, pending_threads=pending_threads)

    await shutdown_checkpointer()


async def test_skill_command_pauses_with_approve_buttons(wired):
    reply = await router.route_inbound(_msg("/skill lead_gen draft outreach"))

    assert "approval gate" in reply.text
    assert len(wired.pending_threads) == 1
    thread_id = next(iter(wired.pending_threads))
    assert (f"/approve {thread_id[:8]}") in [cmd for _, cmd in reply.actions]

    # The channel session is recorded against the run.
    assert wired.pending_threads[thread_id]["session_id"] == "channel-telegram-424242"


async def test_approve_by_prefix_archives(wired):
    await router.route_inbound(_msg("/skill lead_gen draft outreach"))
    thread_id = next(iter(wired.pending_threads))

    reply = await router.route_inbound(_msg(f"/approve {thread_id[:8]}"))

    assert "Approved" in reply.text
    assert not wired.pending_threads
    assert len(list((wired.vault / "30-Archive").glob("*lead_gen*.md"))) == 1


async def test_reject_by_prefix_terminates(wired):
    await router.route_inbound(_msg("/skill lead_gen draft outreach"))
    thread_id = next(iter(wired.pending_threads))

    reply = await router.route_inbound(_msg(f"/reject {thread_id[:8]}"))

    assert "terminated" in reply.text
    assert not wired.pending_threads
    assert list((wired.vault / "30-Archive").glob("*crash*"))


async def test_approve_unknown_prefix_is_helpful(wired):
    reply = await router.route_inbound(_msg("/approve deadbeef"))
    assert "No pending thread" in reply.text


async def test_pending_lists_waiting_threads(wired):
    empty = await router.route_inbound(_msg("/pending"))
    assert "Nothing waiting" in empty.text

    await router.route_inbound(_msg("/skill lead_gen draft outreach"))
    thread_id = next(iter(wired.pending_threads))

    reply = await router.route_inbound(_msg("/pending"))
    assert thread_id[:8] in reply.text
    assert "lead_gen" in reply.text
    assert any(cmd == f"/approve {thread_id[:8]}" for _, cmd in reply.actions)


async def test_free_text_files_to_inbox(wired):
    reply = await router.route_inbound(_msg("call the wholesaler about snail essence"))

    assert "00-Inbox/" in reply.text
    notes = list((wired.vault / "00-Inbox").glob("telegram-*.md"))
    assert len(notes) == 1
    content = notes[0].read_text(encoding="utf-8")
    assert "source: telegram" in content
    assert "call the wholesaler about snail essence" in content


async def test_unknown_command_returns_help(wired):
    reply = await router.route_inbound(_msg("/frobnicate"))
    assert "Unknown command" in reply.text
    assert "/skill" in reply.text


async def test_status_reports_counters(wired):
    reply = await router.route_inbound(_msg("/status"))
    assert "Runs:" in reply.text
    assert "Pending approvals: 0" in reply.text


async def test_skill_command_requires_name(wired):
    reply = await router.route_inbound(_msg("/skill"))
    assert "Usage:" in reply.text
