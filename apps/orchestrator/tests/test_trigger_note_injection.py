"""Tests that triggered skills receive the actual triggering note content."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.execution.service import _TRIGGER_NOTE_MAX_CHARS, _inject_trigger_note
from core.memory.obsidian_client import ObsidianClient


@pytest.fixture
def vault(tmp_path: Path) -> ObsidianClient:
    inbox = tmp_path / "00-Inbox"
    inbox.mkdir(parents=True)
    (inbox / "meeting.md").write_text(
        "---\ntags: [meeting]\n---\n\n# Standup\nDecision: ship the guard.",
        encoding="utf-8",
    )
    return ObsidianClient(tmp_path)


def test_trigger_note_content_prepended(vault: ObsidianClient):
    ctx, sources = _inject_trigger_note(
        "existing rag context", ["10-Knowledge/other.md"], "00-Inbox/meeting.md", client=vault
    )
    assert "Decision: ship the guard." in ctx
    assert ctx.index("Decision: ship the guard.") < ctx.index("existing rag context")
    assert sources[0] == "00-Inbox/meeting.md"
    assert "10-Knowledge/other.md" in sources


def test_trigger_note_source_not_duplicated(vault: ObsidianClient):
    _, sources = _inject_trigger_note(
        "ctx", ["00-Inbox/meeting.md"], "00-Inbox/meeting.md", client=vault
    )
    assert sources.count("00-Inbox/meeting.md") == 1


def test_missing_trigger_note_leaves_context_unchanged(vault: ObsidianClient):
    ctx, sources = _inject_trigger_note("ctx", ["a.md"], "00-Inbox/gone.md", client=vault)
    assert ctx == "ctx"
    assert sources == ["a.md"]


def test_huge_trigger_note_is_truncated(vault: ObsidianClient):
    big = vault.vault_path / "00-Inbox" / "big.md"
    big.write_text("x" * (_TRIGGER_NOTE_MAX_CHARS + 5000), encoding="utf-8")
    ctx, _ = _inject_trigger_note("tail-marker", [], "00-Inbox/big.md", client=vault)
    assert len(ctx) < _TRIGGER_NOTE_MAX_CHARS + 1000
    assert "tail-marker" in ctx
