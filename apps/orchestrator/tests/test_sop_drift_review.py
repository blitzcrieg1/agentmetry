"""vault_fs read_jsonl_tail and sop_drift_review learning archive."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import api.routes.skills as skills_route
import core.execution.service as service
import core.graphs.checkpointer as checkpointer_module
import core.graphs.node_events as node_events_module
import core.graphs.pipeline_graph as pipeline_graph_module
from core.drivers.host import MCPHost
from core.drivers.spec import DriverSpec
from api.routes.skills import ApprovalRequest, approve_skill
from core.config import settings
from core.graphs.checkpointer import init_checkpointer, shutdown_checkpointer
from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient
from core.telemetry.pending_store import PendingThreadStore

_ORCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ORCH_ROOT / "tools"))
import vault_fs_server as vfs  # noqa: E402


class FakeRAG:
    async def query(self, *args, **kwargs):
        return []

    async def summarize_context(self, chunks, max_tokens=500):
        return ""


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    feedback = tmp_path / ".system" / "feedback"
    feedback.mkdir(parents=True)
    entries = [
        {
            "ts": "2026-07-08T19:43:29+00:00",
            "thread_id": "abc12345-0000-0000-0000-000000000001",
            "skill_name": "customer_reply",
            "original_draft": "We will follow up within one business day.",
            "modified_input": "We will follow up within one business day.\n\nWarehouse team within 24 hours.",
            "char_delta": 40,
        },
    ]
    log = feedback / "edit-log.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    for rel in ("10-SOPs", "10-SOPs/Learnings"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "10-SOPs" / "shipping-faq.md").write_text("# Shipping\nEU 3-5 days", encoding="utf-8")
    (tmp_path / "10-SOPs" / "returns-policy.md").write_text("# Returns\n14 days", encoding="utf-8")
    (tmp_path / "10-SOPs" / "customer-tone.md").write_text("# Tone\nProfessional", encoding="utf-8")
    return tmp_path


def test_read_jsonl_tail_formats_markdown(vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vfs, "VAULT", vault.resolve())
    out = vfs.read_jsonl_tail(".system/feedback/edit-log.jsonl", limit=20)
    assert "Correction 1" in out
    assert "customer_reply" in out
    assert "Warehouse team within 24 hours" in out
    assert "one business day" in out


def test_read_jsonl_tail_empty_file(vault: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vfs, "VAULT", vault.resolve())
    empty = vault / ".system" / "feedback" / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert "empty" in vfs.read_jsonl_tail(".system/feedback/empty.jsonl").lower()


def test_write_sop_learning_patch(vault: Path):
    client = ObsidianClient(vault)
    path = client.write_sop_learning_patch(
        "## Proposed change\nUpdate shipping FAQ.",
        thread_id="t-patch-1",
    )
    assert path.parent.name == "Learnings"
    assert path.name.startswith("SOP-Patch-")
    text = path.read_text(encoding="utf-8")
    assert "sop-learning-patch" in text
    assert "Update shipping FAQ" in text


@pytest.fixture
async def wired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo_skill = Path(__file__).resolve().parents[3] / "vault" / ".system" / "skill-definitions" / "sop_drift_review.yaml"
    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("sop_drift_review.yaml").write_text(
        repo_skill.read_text(encoding="utf-8"), encoding="utf-8"
    )
    feedback = vault / ".system" / "feedback"
    feedback.mkdir(parents=True)
    feedback.joinpath("edit-log.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-07-08T19:43:29+00:00",
                "thread_id": "abc12345-0000-0000-0000-000000000001",
                "skill_name": "customer_reply",
                "original_draft": "Follow up in one business day.",
                "modified_input": "Follow up in one business day.\n\n24h warehouse check.",
                "char_delta": 25,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for name, body in {
        "shipping-faq.md": "# Shipping\nEU 3-5 days",
        "returns-policy.md": "# Returns\n14 days",
        "customer-tone.md": "# Tone\nProfessional",
        "client-reply.md": "# Reply\nBe brief",
    }.items():
        (vault / "10-SOPs").mkdir(parents=True, exist_ok=True)
        (vault / "10-SOPs" / name).write_text(body, encoding="utf-8")
    (vault / "10-SOPs" / "Learnings").mkdir(parents=True)

    # Prior tests (e.g. test_registry) may leave a global checkpointer alive —
    # init_checkpointer() no-ops when one exists, so tear down first.
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
    import core.drivers.host as driver_host

    monkeypatch.setattr(driver_host, "_host", host)
    monkeypatch.setattr(pipeline_graph_module, "get_mcp_host", lambda: host)

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
    assert "sop_drift_review" in registry.list_registered()

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

    yield obsidian

    await shutdown_checkpointer()


async def test_sop_drift_review_pauses_for_approval(wired: ObsidianClient):
    result = await service.run_skill("sop_drift_review", "20", "sess-drift")
    assert result["status"] == "waiting_for_input"
    assert result["thread_id"]


async def test_sop_drift_review_archives_to_learnings(wired: ObsidianClient):
    result = await service.run_skill("sop_drift_review", "20", "sess-drift-2")
    thread_id = result["thread_id"]

    outcome = await approve_skill(ApprovalRequest(thread_id=thread_id, approved=True))
    assert outcome["status"] == "approved"
    archive = Path(outcome["archive_path"])
    assert archive.parent.name == "Learnings"
    assert archive.name.startswith("SOP-Patch-")
