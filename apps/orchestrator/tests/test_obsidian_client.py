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


def test_closeout_notes_never_overwrite(vault: ObsidianClient):
    p1 = vault.write_closeout_note("summarize_meeting", "first result", thread_id="abc12345")
    p2 = vault.write_closeout_note("summarize_meeting", "second result", thread_id="abc12345")
    assert p1 != p2
    assert "first result" in p1.read_text(encoding="utf-8")
    assert "second result" in p2.read_text(encoding="utf-8")


def test_closeout_filename_has_skill_and_thread(vault: ObsidianClient):
    path = vault.write_closeout_note("weekly_review", "r", thread_id="deadbeef-1234")
    assert "weekly_review" in path.name
    assert "deadbeef" in path.name
    assert "outreach" not in path.name


def test_closeout_result_written_once(vault: ObsidianClient):
    path = vault.write_closeout_note("summarize_meeting", "UNIQUE_RESULT_TOKEN", thread_id="t1")
    content = path.read_text(encoding="utf-8")
    assert content.count("UNIQUE_RESULT_TOKEN") == 1
    assert "thread_id: t1" in content
