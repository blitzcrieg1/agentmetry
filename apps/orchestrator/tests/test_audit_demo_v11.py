"""audit_demo end-to-end — schema v1.1 initiator + gated_action on real bus path."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.routes.skills as skills_route
import core.drivers.host as driver_host
import core.execution.service as service
import core.graphs.checkpointer as checkpointer_module
import core.graphs.node_events as node_events_module
import core.graphs.pipeline_graph as pipeline_graph_module
from api.routes.skills import ApprovalRequest, approve_skill
from core.audit.canonical import normalize_outbox_row
from core.bus.bus import bus
from core.bus.events import (
    RUN_APPROVAL_DENIED,
    RUN_APPROVAL_GRANTED,
    RUN_STARTED,
    RUN_WAITING,
    TOOL_CALLED,
)
from core.config import settings
from core.drivers.host import MCPHost
from core.drivers.spec import DriverSpec
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient
from core.telemetry.pending_store import PendingThreadStore

_ORCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ORCH_ROOT / "tools"))


class FakeRAG:
    async def query(self, *args, **kwargs):
        return []

    async def summarize_context(self, chunks, max_tokens=500):
        return ""


def _drain(sub, limit: int = 50) -> list:
    out = []
    for _ in range(limit):
        try:
            out.append(sub.queue.get_nowait())
        except Exception:
            break
    return out


def _row_from_event(ev) -> dict:
    return {
        "seq": ev.seq,
        "ts": ev.ts,
        "topic": ev.topic,
        "session_id": ev.session_id,
        "thread_id": ev.thread_id,
        "payload": ev.payload,
    }


@pytest.fixture
async def audit_demo_wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_skill = (
        Path(__file__).resolve().parents[3]
        / "vault"
        / ".system"
        / "skill-definitions"
        / "audit_demo.yaml"
    )
    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("audit_demo.yaml").write_text(
        repo_skill.read_text(encoding="utf-8"), encoding="utf-8"
    )
    inbox = vault / "00-Inbox"
    inbox.mkdir(parents=True)
    inbox.joinpath("audit-demo-note.md").write_text(
        "# Demo\nAgentAudit dogfood input.\n", encoding="utf-8"
    )

    await shutdown_checkpointer()

    host = MCPHost()
    vfs_script = _ORCH_ROOT / "tools" / "vault_fs_server.py"
    spec = DriverSpec(
        name="vault_fs",
        transport="stdio",
        command=sys.executable,
        args=[str(vfs_script), str(vault)],
    )
    assert await host.mount(spec)
    monkeypatch.setattr(driver_host, "_host", host)
    monkeypatch.setattr(pipeline_graph_module, "get_mcp_host", lambda: host)

    monkeypatch.setattr(settings, "vault_path", vault)
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "operator_id", "home-lab")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(checkpointer_module, "_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(
        node_events_module, "node_events_path", lambda: tmp_path / "node-events.jsonl"
    )
    await init_checkpointer()

    obsidian = ObsidianClient(vault)
    registry = SkillRegistry(obsidian)
    registry.reload()
    assert "audit_demo" in registry.list_registered()

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

    sub = bus.subscribe(
        "audit-v11",
        topics={
            RUN_STARTED,
            TOOL_CALLED,
            RUN_WAITING,
            RUN_APPROVAL_GRANTED,
            RUN_APPROVAL_DENIED,
        },
    )

    yield SimpleNamespace(vault=vault, sub=sub, pending_threads=pending_threads)

    await shutdown_checkpointer()


async def test_audit_demo_waiting_has_gated_action(audit_demo_wired):
    _drain(audit_demo_wired.sub)
    result = await service.run_skill(
        "audit_demo",
        "00-Inbox/audit-demo-note.md",
        "sess-v11",
        triggered_by="manual",
    )
    assert result["status"] == "waiting_for_input"
    events = _drain(audit_demo_wired.sub)
    by_topic = {e.topic: e for e in events}

    waiting = by_topic.get(RUN_WAITING)
    assert waiting is not None
    assert waiting.payload.get("skill") == "audit_demo"
    assert waiting.payload["initiator"]["actor_type"] == "human"
    gated = waiting.payload.get("gated_action")
    assert gated is not None
    assert gated["tool"] == "vault_fs.read_note"
    assert gated["server"] == "vault_fs"
    assert len(gated["input_hash"]) == 64

    canonical = normalize_outbox_row(_row_from_event(waiting))
    assert canonical["schema_version"] == "1.1.0"
    assert canonical["agent"]["skill_id"] == "audit_demo"
    assert canonical["gated_action"]["tool"] == "vault_fs.read_note"


async def test_audit_demo_approve_and_reject_emit_v11(audit_demo_wired):
    _drain(audit_demo_wired.sub)

    approve_run = await service.run_skill(
        "audit_demo",
        "00-Inbox/audit-demo-note.md",
        "sess-approve",
    )
    tid_ok = approve_run["thread_id"]
    _drain(audit_demo_wired.sub)

    reject_run = await service.run_skill(
        "audit_demo",
        "00-Inbox/audit-demo-note.md",
        "sess-reject",
    )
    tid_no = reject_run["thread_id"]
    _drain(audit_demo_wired.sub)

    await approve_skill(ApprovalRequest(thread_id=tid_ok, approved=True))
    await approve_skill(ApprovalRequest(thread_id=tid_no, approved=False))

    events = _drain(audit_demo_wired.sub)
    granted = [e for e in events if e.topic == RUN_APPROVAL_GRANTED]
    denied = [e for e in events if e.topic == RUN_APPROVAL_DENIED]
    assert len(granted) == 1
    assert len(denied) == 1

    canon_grant = normalize_outbox_row(_row_from_event(granted[0]))
    assert canon_grant["initiator"]["actor_type"] == "human"
    assert canon_grant["actor"]["type"] == "user"
    assert canon_grant["agent"]["skill_id"] == "audit_demo"

    canon_deny = normalize_outbox_row(_row_from_event(denied[0]))
    assert canon_deny["action"]["outcome"] == "denied"


async def test_cron_run_stamps_autonomous_initiator(audit_demo_wired):
    _drain(audit_demo_wired.sub)
    await service.run_skill(
        "audit_demo",
        "00-Inbox/audit-demo-note.md",
        "sess-cron",
        triggered_by="cron",
    )
    events = _drain(audit_demo_wired.sub)
    started = next(e for e in events if e.topic == RUN_STARTED)
    assert started.payload["initiator"]["actor_type"] == "autonomous"
    assert started.payload["initiator"]["trigger"] == "cron"

    canonical = normalize_outbox_row(_row_from_event(started))
    assert canonical["actor"]["type"] == "agent"
