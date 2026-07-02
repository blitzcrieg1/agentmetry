"""Tests for vault path traversal protection."""

from pathlib import Path

import pytest

from core.memory.obsidian_client import ObsidianClient


@pytest.fixture
def vault(tmp_path: Path) -> ObsidianClient:
    notes = tmp_path / "10-Knowledge"
    notes.mkdir(parents=True)
    (notes / "safe.md").write_text("# Safe note", encoding="utf-8")
    return ObsidianClient(tmp_path)


def test_read_note_valid_path(vault: ObsidianClient):
    content = vault.read_note("10-Knowledge/safe.md")
    assert content == "# Safe note"


def test_read_note_rejects_traversal(vault: ObsidianClient):
    assert vault.read_note("../../etc/passwd") is None
    assert vault.read_note("10-Knowledge/../../../outside.md") is None


def test_read_note_missing_file(vault: ObsidianClient):
    assert vault.read_note("10-Knowledge/missing.md") is None
