"""FTS5 vault index — jailing, search, and upsert behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.memory.fts_index import VaultFTSIndex, should_index


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "00-Inbox").mkdir()
    (tmp_path / "10-SOPs").mkdir()
    (tmp_path / "20-Active-Loops").mkdir()
    (tmp_path / ".system").mkdir()
    return tmp_path


@pytest.fixture
def fts(vault: Path, tmp_path: Path) -> VaultFTSIndex:
    return VaultFTSIndex(db_path=tmp_path / "fts.db", vault_root=vault)


def test_should_index_rules():
    assert should_index("00-Inbox/note.md")
    assert should_index(".system/GOALS.md")
    assert should_index(".system/AGENTS.md")
    assert not should_index("20-Active-Loops/running.md")
    assert not should_index(".system/skill-definitions/foo.yaml")
    assert not should_index(".system/skill-definitions/foo.md")


def test_reindex_and_search(vault: Path, fts: VaultFTSIndex):
    (vault / "10-SOPs" / "client-reply.md").write_text(
        "Always confirm pricing before quoting Acme Corp.",
        encoding="utf-8",
    )
    (vault / ".system" / "GOALS.md").write_text(
        "---\ntype: system\n---\nDogfood email autopilot weekly.",
        encoding="utf-8",
    )
    (vault / "20-Active-Loops" / "skip.md").write_text("ephemeral", encoding="utf-8")

    count = fts.reindex()
    assert count == 2

    hits = fts.search("Acme pricing")
    assert len(hits) == 1
    assert hits[0]["path"] == "10-SOPs/client-reply.md"
    assert "Acme" in hits[0]["snippet"]


def test_upsert_file_adds_and_removes(vault: Path, fts: VaultFTSIndex):
    note = vault / "00-Inbox" / "new.md"
    note.write_text("Quarterly invoice due August first.", encoding="utf-8")
    assert fts.upsert_file(note) is True
    assert fts.search("invoice")[0]["path"] == "00-Inbox/new.md"

    note.unlink()
    fts.upsert_file(note)
    assert fts.search("invoice") == []


def test_empty_query_returns_nothing(fts: VaultFTSIndex):
    assert fts.search("") == []
    assert fts.search("   ") == []
