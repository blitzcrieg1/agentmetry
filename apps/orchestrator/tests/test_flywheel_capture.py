"""Implicit diff flywheel — edit capture and telemetry."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

import api.routes.skills as skills_route
import core.execution.service as service
import core.graphs.checkpointer as checkpointer_module
import core.graphs.node_events as node_events_module
import core.learning.flywheel as flywheel_module
from api.routes.skills import ApprovalRequest, approve_skill
from core.bus.events import FLYWHEEL_CAPTURE
from core.config import settings
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.graphs.registry import SkillRegistry
from core.learning.flywheel import (
    EDIT_LOG_REL,
    FLYWHEEL_MESSAGE,
    append_edit_log,
    build_edit_entry,
    drafts_differ,
    schedule_edit_capture,
)
from core.memory.obsidian_client import ObsidianClient
from core.telemetry.pending_store import PendingThreadStore


class FakeRAG:
    async def query(self, *args, **kwargs):
        return []

    async def summarize_context(self, chunks, max_tokens=500):
        return ""


SKILL_YAML = {
    "name": "lead_gen",
    "display_name": "Lead Gen",
    "description": "test skill",
    "graph": "lead_gen",
    "approval_threshold": 0.9,
    "nodes": ["planner", "researcher", "writer", "critic", "human_approval", "finalize"],
}


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "lead_gen.yaml").write_text(yaml.dump(SKILL_YAML), encoding="utf-8")

    monkeypatch.setattr(settings, "vault_path", vault)
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
    pending_store = PendingThreadStore(db_url)
    pending_threads: dict = {}

    for module in (service, skills_route):
        monkeypatch.setattr(module, "obsidian", obsidian)
        monkeypatch.setattr(module, "pending_threads", pending_threads)
        monkeypatch.setattr(module, "skill_registry", registry)
    monkeypatch.setattr(service, "pending_store", pending_store)
    monkeypatch.setattr(service, "rag", FakeRAG())
    monkeypatch.setattr(service, "log_run", lambda event: None)
    monkeypatch.setattr(service, "append_vault_run_log", lambda line: None)

    yield obsidian, pending_threads

    await shutdown_checkpointer()


def test_drafts_differ_ignores_whitespace():
    assert not drafts_differ("Hello\n", "  Hello  ")
    assert drafts_differ("Hello", "Hello world")


def test_build_edit_entry_schema():
    entry = build_edit_entry(
        thread_id="t1",
        skill_name="customer_reply",
        original_draft="AI draft",
        modified_input="Operator draft",
    )
    assert entry["thread_id"] == "t1"
    assert entry["skill_name"] == "customer_reply"
    assert entry["original_draft"] == "AI draft"
    assert entry["modified_input"] == "Operator draft"
    assert "ts" in entry
    assert entry["char_delta"] == len("Operator draft") - len("AI draft")


def test_append_edit_log_writes_jsonl(wired):
    obsidian, _ = wired
    append_edit_log(
        build_edit_entry(
            thread_id="t1",
            skill_name="customer_reply",
            original_draft="before",
            modified_input="after",
        ),
        client=obsidian,
    )
    log_path = obsidian.vault_path / EDIT_LOG_REL
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["original_draft"] == "before"
    assert row["modified_input"] == "after"


async def test_approve_with_edit_captures_jsonl_and_emits_flywheel(wired, monkeypatch):
    obsidian, pending_threads = wired
    captured: list[dict] = []
    real_publish = flywheel_module.bus.publish

    def spy_publish(topic, payload, *, session_id="", thread_id=""):
        if topic == FLYWHEEL_CAPTURE:
            captured.append(payload)
        return real_publish(topic, payload, session_id=session_id, thread_id=thread_id)

    monkeypatch.setattr(flywheel_module.bus, "publish", spy_publish)

    result = await service.run_skill("lead_gen", "draft outreach", "sess-flywheel")
    assert result["status"] == "waiting_for_input"
    thread_id = result["thread_id"]

    graph = service.skill_registry.get("lead_gen")
    snapshot = await graph.aget_state(pending_threads[thread_id]["config"])
    original_draft = snapshot.values["draft"]
    modified = f"{original_draft}\n\nAdded by operator."

    outcome = await approve_skill(
        ApprovalRequest(thread_id=thread_id, approved=True, modified_input=modified)
    )
    assert outcome["status"] == "approved"

    await asyncio.sleep(0.05)

    log_path = obsidian.vault_path / EDIT_LOG_REL
    assert log_path.exists()
    row = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["thread_id"] == thread_id
    assert row["skill_name"] == "lead_gen"
    assert row["original_draft"] == original_draft
    assert row["modified_input"] == modified

    assert len(captured) == 1
    assert captured[0]["type"] == "flywheel_capture"
    assert captured[0]["message"] == FLYWHEEL_MESSAGE
    assert captured[0]["thread_id"] == thread_id


async def test_approve_without_edit_skips_flywheel(wired, monkeypatch):
    obsidian, _ = wired
    captured: list[dict] = []
    real_publish = flywheel_module.bus.publish

    def spy_publish(topic, payload, *, session_id="", thread_id=""):
        if topic == FLYWHEEL_CAPTURE:
            captured.append(payload)
        return real_publish(topic, payload, session_id=session_id, thread_id=thread_id)

    monkeypatch.setattr(flywheel_module.bus, "publish", spy_publish)

    result = await service.run_skill("lead_gen", "draft outreach", "sess-clean")
    thread_id = result["thread_id"]

    outcome = await approve_skill(
        ApprovalRequest(thread_id=thread_id, approved=True, modified_input=None)
    )
    assert outcome["status"] == "approved"
    await asyncio.sleep(0.05)

    log_path = obsidian.vault_path / EDIT_LOG_REL
    assert not log_path.exists()
    assert captured == []


async def test_schedule_edit_capture_publishes_event(tmp_path: Path):
    vault = tmp_path / "vault"
    client = ObsidianClient(vault)
    captured: list[dict] = []
    real_publish = flywheel_module.bus.publish

    def spy_publish(topic, payload, *, session_id="", thread_id=""):
        if topic == FLYWHEEL_CAPTURE:
            captured.append(payload)
        return real_publish(topic, payload, session_id=session_id, thread_id=thread_id)

    flywheel_module.bus.publish = spy_publish  # type: ignore[method-assign]

    await schedule_edit_capture(
        thread_id="unit-t",
        skill_name="customer_reply",
        session_id="sess-u",
        original_draft="Draft A",
        modified_input="Draft B",
        client=client,
    )
    await asyncio.sleep(0.05)

    log_path = vault / EDIT_LOG_REL
    assert log_path.exists()
    row = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert row["modified_input"] == "Draft B"
    assert len(captured) == 1
    assert captured[0]["message"] == FLYWHEEL_MESSAGE

    flywheel_module.bus.publish = real_publish  # type: ignore[method-assign]
