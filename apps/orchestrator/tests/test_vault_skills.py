"""The vault YAMLs actually shipped in this repo must load and compile."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient

_REPO_VAULT = Path(__file__).resolve().parents[3] / "vault"


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> SkillRegistry:
    from langgraph.checkpoint.memory import InMemorySaver

    monkeypatch.setattr("core.graphs.checkpointer.get_checkpointer", lambda: InMemorySaver())
    return SkillRegistry(ObsidianClient(_REPO_VAULT))


def test_shipped_skills_all_compile(registry: SkillRegistry):
    registry.reload()
    registered = set(registry.list_registered())
    assert "audit_demo" in registered


def test_shipped_default_inputs_point_at_real_notes():
    obsidian = ObsidianClient(_REPO_VAULT)
    for skill in obsidian.list_skills():
        default_input = skill.get("default_input")
        if not default_input or not str(default_input).endswith(".md"):
            continue
        assert obsidian.read_note(str(default_input)) is not None, (
            f"{skill['name']}: default_input '{default_input}' is not a note in the vault"
        )


def test_shipped_pipeline_skills_declare_governed_tools():
    obsidian = ObsidianClient(_REPO_VAULT)
    for skill in obsidian.list_skills():
        if skill.get("graph") != "pipeline":
            continue
        node_tools = skill.get("node_tools") or {}
        allow = skill.get("tools") or []
        for step_calls in node_tools.values():
            for call in step_calls:
                from fnmatch import fnmatch

                assert any(fnmatch(call["tool"], pattern) for pattern in allow), (
                    f"{skill['name']}: node_tools uses {call['tool']} "
                    f"but tools allowlist is {allow}"
                )
