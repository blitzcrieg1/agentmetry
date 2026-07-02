"""Dynamic skill graph registry — maps vault YAML definitions to LangGraph instances."""

from __future__ import annotations

from typing import Any

from core.graphs.lead_gen_graph import compile_lead_gen_graph
from core.graphs.meeting_graph import build_meeting_graph
from core.graphs.checkpointer import checkpointer
from core.memory.obsidian_client import ObsidianClient


# Graph builders keyed by the `graph` field in skill YAML
_GRAPH_BUILDERS: dict[str, Any] = {
    "lead_gen": compile_lead_gen_graph,
    "summarize_meeting": lambda: build_meeting_graph().compile(checkpointer=checkpointer),
}


class SkillRegistry:
    """Auto-discovers skills from vault YAML and resolves graph implementations."""

    def __init__(self, obsidian: ObsidianClient):
        self.obsidian = obsidian
        self._graphs: dict[str, Any] = {}
        self._refresh()

    def _refresh(self) -> None:
        self._graphs.clear()
        for skill in self.obsidian.list_skills():
            skill_id = skill.get("id") or skill.get("name")
            graph_key = skill.get("graph", skill_id)
            builder = _GRAPH_BUILDERS.get(graph_key)
            if builder and skill_id:
                self._graphs[skill_id] = builder()

    def reload(self) -> None:
        """Re-scan vault skill definitions (call after vault changes)."""
        self._refresh()

    def get(self, skill_name: str) -> Any | None:
        if skill_name not in self._graphs:
            self._refresh()
        return self._graphs.get(skill_name)

    def list_registered(self) -> list[str]:
        return list(self._graphs.keys())

    def register_builder(self, graph_key: str, builder: Any) -> None:
        """Register a new graph builder at runtime."""
        _GRAPH_BUILDERS[graph_key] = builder
        self._refresh()

    @staticmethod
    def available_graph_types() -> list[str]:
        return list(_GRAPH_BUILDERS.keys())
