"""Universal webhook ingress — vault drop + skill enqueue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from core.config import settings
from core.graphs.registry import SkillRegistry
from core.ingress.webhook import payload_to_markdown
from core.memory.obsidian_client import ObsidianClient

WOOCOMMERCE_PAYLOAD = {
    "id": 5821,
    "status": "processing",
    "customer_email": "maria@example.com",
    "total": "49.99",
    "line_items": [{"name": "Hydrating Snail Essence", "quantity": 1, "sku": "SNAIL-01"}],
}

INBOX_TRIAGE_YAML = {
    "name": "inbox_triage",
    "display_name": "Inbox Triage",
    "description": "Triage an inbox note",
    "graph": "pipeline",
    "tools": ["vault_fs.read_note"],
    "nodes": ["triage", "finalize"],
    "node_tools": {
        "triage": [{"tool": "vault_fs.read_note", "args": {"path": "{user_input}"}, "output": "note_text"}]
    },
    "node_prompts": {"triage": "Triage:\n{note_text}"},
    "max_cost_per_run": 0.05,
}


@pytest.fixture
def ingress_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import api.routes.ingress as ingress_route
    from langgraph.checkpoint.memory import InMemorySaver

    vault = tmp_path / "vault"
    skill_dir = vault / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "inbox_triage.yaml").write_text(yaml.dump(INBOX_TRIAGE_YAML), encoding="utf-8")
    (vault / "00-Inbox").mkdir(parents=True)

    monkeypatch.setattr(settings, "vault_path", vault)
    monkeypatch.setattr(settings, "api_key", "test-secret")
    monkeypatch.setattr(
        "core.graphs.checkpointer.get_checkpointer", lambda: InMemorySaver()
    )

    obsidian = ObsidianClient(vault)
    registry = SkillRegistry(obsidian)
    registry.reload()

    run_calls: list[dict] = []

    async def fake_run_skill(skill_name, user_input, session_id, **kwargs):
        run_calls.append(
            {
                "skill_name": skill_name,
                "user_input": user_input,
                "session_id": session_id,
                **kwargs,
            }
        )
        return {"status": "completed", "thread_id": "ingress-thread-1"}

    monkeypatch.setattr(ingress_route, "obsidian", obsidian)
    monkeypatch.setattr(ingress_route, "skill_registry", registry)
    monkeypatch.setattr(ingress_route, "run_skill", fake_run_skill)

    from api.main import app

    with TestClient(app) as client:
        yield client, vault, run_calls


def test_payload_to_markdown_frontmatter_and_table():
    md = payload_to_markdown(
        WOOCOMMERCE_PAYLOAD,
        source="woocommerce",
        target_skill="customer_reply",
    )
    assert "type: ingress" in md or "type:" in md
    assert "source: woocommerce" in md
    assert "target_skill: customer_reply" in md
    assert "customer_email" in md
    assert "## line_items" in md
    assert "Hydrating Snail Essence" in md
    assert "| Field | Value |" in md


def test_ingress_requires_api_key(ingress_env):
    client, _, _ = ingress_env
    res = client.post(
        "/api/v1/ingress",
        json=WOOCOMMERCE_PAYLOAD,
        headers={"X-Target-Skill": "inbox_triage", "X-Source-Name": "woocommerce"},
    )
    assert res.status_code == 401


def test_ingress_unknown_skill_returns_404(ingress_env):
    client, _, _ = ingress_env
    res = client.post(
        "/api/v1/ingress",
        json=WOOCOMMERCE_PAYLOAD,
        headers={
            "X-API-Key": "test-secret",
            "X-Target-Skill": "nonexistent_skill",
            "X-Source-Name": "woocommerce",
        },
    )
    assert res.status_code == 404


def test_ingress_woocommerce_creates_vault_note_and_runs_skill(ingress_env):
    client, vault, run_calls = ingress_env
    res = client.post(
        "/api/v1/ingress",
        json=WOOCOMMERCE_PAYLOAD,
        headers={
            "X-API-Key": "test-secret",
            "X-Target-Skill": "inbox_triage",
            "X-Source-Name": "woocommerce",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "completed"
    assert body["skill"] == "inbox_triage"
    assert body["source"] == "woocommerce"
    assert body["session_id"] == "autonomous-woocommerce"
    assert body["vault_path"].startswith("00-Inbox/ingress-woocommerce-")

    note_path = vault / body["vault_path"]
    assert note_path.is_file()
    text = note_path.read_text(encoding="utf-8")
    assert "maria@example.com" in text
    assert "5821" in text

    assert len(run_calls) == 1
    call = run_calls[0]
    assert call["skill_name"] == "inbox_triage"
    assert call["user_input"] == body["vault_path"]
    assert call["session_id"] == "autonomous-woocommerce"
    assert call["triggered_by"] == "ingress"
    assert call["trigger_file_path"] == body["vault_path"]


def test_write_ingress_note_only_allows_ingress_prefix(tmp_path: Path):
    client = ObsidianClient(tmp_path)
    path = client.write_ingress_note("zapier", "# Event\n")
    assert path.name.startswith("ingress-zapier-")
    with pytest.raises(PermissionError):
        client._write_text(tmp_path / "00-Inbox" / "manual-note.md", "nope")
