"""SOP path resolution and injection into skill context."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.execution.service import _append_sop_context, _fetch_skill_context, _resolve_sop_paths
from core.memory.obsidian_client import ObsidianClient


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    for rel in (
        "10-SOPs",
        "10-Knowledge/SOPs",
        "10-Knowledge/clients",
        ".system",
    ):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "10-SOPs" / "client-reply.md").write_text(
        "Never quote pricing without vault confirmation.",
        encoding="utf-8",
    )
    (tmp_path / "10-Knowledge" / "SOPs" / "extra-policy.md").write_text(
        "Always offer a call for angry threads.",
        encoding="utf-8",
    )
    (tmp_path / ".system" / "GOALS.md").write_text("Dogfood email.", encoding="utf-8")
    return tmp_path


def test_resolve_sop_paths_expands_globs(vault: Path):
    paths = _resolve_sop_paths(
        {
            "sop_paths": [
                "10-SOPs/client-reply.md",
                "10-Knowledge/SOPs/*.md",
            ]
        },
        vault,
    )
    assert paths == [
        "10-SOPs/client-reply.md",
        "10-Knowledge/SOPs/extra-policy.md",
    ]


def test_append_sop_context_injects_before_other_blocks(vault: Path, monkeypatch: pytest.MonkeyPatch):
    import core.execution.service as service

    monkeypatch.setattr(service, "obsidian", ObsidianClient(vault))
    blocks: list[str] = ["[Source: .system/GOALS.md]\ngoals"]
    sources = [".system/GOALS.md"]

    _append_sop_context(blocks, sources, {"sop_paths": ["10-SOPs/client-reply.md"]}, vault_path=vault)

    assert len(blocks) == 2
    assert "[SOP: 10-SOPs/client-reply.md]" in blocks[1]
    assert "Never quote pricing" in blocks[1]
    assert sources[1] == "10-SOPs/client-reply.md"


@pytest.mark.asyncio
async def test_fetch_skill_context_prioritizes_sops(vault: Path, monkeypatch: pytest.MonkeyPatch):
    import core.execution.service as service

    class FakeRAG:
        async def query(self, *args, **kwargs):
            return []

        async def summarize_context(self, chunks):
            return ""

    class FakeFTS:
        def search(self, query, limit=5):
            return [{"path": "00-Inbox/other.md", "snippet": "other context"}]

    monkeypatch.setattr(service, "obsidian", ObsidianClient(vault))
    monkeypatch.setattr(service.settings, "vault_path", vault)
    monkeypatch.setattr(service, "rag", FakeRAG())
    monkeypatch.setattr(service, "fts", FakeFTS())

    context, sources = await _fetch_skill_context(
        "pricing question",
        {"sop_paths": ["10-SOPs/client-reply.md", "10-Knowledge/SOPs/*.md"]},
    )
    assert "[SOP: 10-SOPs/client-reply.md]" in context
    assert "Never quote pricing" in context
    assert "10-Knowledge/SOPs/extra-policy.md" in sources
    assert sources.index("10-SOPs/client-reply.md") < sources.index("00-Inbox/other.md")
