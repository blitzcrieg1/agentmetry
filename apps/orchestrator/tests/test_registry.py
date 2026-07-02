"""Tests for skill registry discovery."""

from pathlib import Path

import pytest

from core.graphs.registry import SkillRegistry
from core.memory.obsidian_client import ObsidianClient


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    skill_dir = tmp_path / ".system" / "skill-definitions"
    skill_dir.mkdir(parents=True)
    (skill_dir / "weekly_review.yaml").write_text(
        """
name: weekly_review
display_name: Weekly Review
description: Test skill
graph: weekly_review
nodes:
  - collect
  - analyze
  - prioritize
  - finalize
""".strip(),
        encoding="utf-8",
    )
    return SkillRegistry(ObsidianClient(tmp_path))


def test_weekly_review_registered(registry: SkillRegistry):
    assert "weekly_review" in registry.list_registered()


def test_available_graph_types():
    types = SkillRegistry.available_graph_types()
    assert "lead_gen" in types
    assert "weekly_review" in types
