"""Tests for skill registry discovery."""

import asyncio
from pathlib import Path

import pytest

from core.graphs.checkpointer import init_checkpointer
from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient


@pytest.fixture
def registry(tmp_path: Path):
    skill_dir = tmp_path / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "audit_demo.yaml").write_text(
        """
name: audit_demo
display_name: AgentAudit Demo
description: Test skill
graph: pipeline
tools:
  - vault_fs.read_note
tool_only_nodes:
  - read
nodes:
  - read
  - human_approval
  - archive
node_tools:
  read:
    - tool: vault_fs.read_note
      args:
        path: "{user_input}"
      output: note_text
""".strip(),
        encoding="utf-8",
    )
    reg = SkillRegistry(ObsidianClient(tmp_path))
    asyncio.run(init_checkpointer())
    reg.reload()
    return reg


def test_audit_demo_registered(registry: SkillRegistry):
    assert "audit_demo" in registry.list_registered()


def test_available_graph_types():
    types = SkillRegistry.available_graph_types()
    assert types == ["pipeline"]
