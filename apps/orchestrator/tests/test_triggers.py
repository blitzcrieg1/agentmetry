"""Tests for trigger rules and vault write whitelist."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.memory.obsidian_client import ObsidianClient
from core.scheduler.rules import load_trigger_rules, note_matches_rule


@pytest.fixture
def vault_tmp(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "00-Inbox").mkdir(parents=True)
    (vault / ".system" / "trigger-rules").mkdir(parents=True)
    (vault / ".system" / "skill-definitions").mkdir(parents=True)
    rule = {
        "id": "inbox-meeting",
        "type": "vault_watch",
        "enabled": True,
        "skill": "summarize_meeting",
        "match": {
            "path_glob": "00-Inbox/*.md",
            "frontmatter": {"tags": ["meeting"]},
        },
        "user_input_template": "Summarize {{ trigger.file_path }}",
    }
    with open(vault / ".system" / "trigger-rules" / "inbox.yaml", "w", encoding="utf-8") as f:
        yaml.dump(rule, f)
    return vault


def test_load_trigger_rules(vault_tmp: Path):
    rules = load_trigger_rules(vault_tmp)
    assert len(rules) == 1
    assert rules[0].skill == "summarize_meeting"


def test_note_matches_rule(vault_tmp: Path):
    note = vault_tmp / "00-Inbox" / "standup.md"
    note.write_text(
        "---\ntags:\n  - meeting\n---\n\n# Standup\n",
        encoding="utf-8",
    )
    obsidian = ObsidianClient(vault_tmp)
    rules = load_trigger_rules(vault_tmp)
    assert note_matches_rule(rules[0], "00-Inbox/standup.md", obsidian)


def test_write_whitelist_blocks_escape(vault_tmp: Path):
    obsidian = ObsidianClient(vault_tmp)
    with pytest.raises(PermissionError):
        obsidian.write_system_note("../escape.md", "bad")


def test_write_whitelist_allows_archive(vault_tmp: Path):
    obsidian = ObsidianClient(vault_tmp)
    path = obsidian.write_closeout_note("test_skill", "result body")
    assert path.exists()
