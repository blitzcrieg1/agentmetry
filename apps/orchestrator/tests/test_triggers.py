"""Tests for trigger rules and vault write whitelist."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.memory.obsidian_client import ObsidianClient
from core.scheduler.rules import (
    TriggerRule,
    load_trigger_rules,
    note_matches_rule,
    render_user_input,
)


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


def _rule(**overrides) -> TriggerRule:
    base = {
        "id": "r",
        "type": "vault_watch",
        "skill": "summarize_note",
        "enabled": True,
        "path_glob": "00-Inbox/*.md",
    }
    base.update(overrides)
    return TriggerRule(**base)


def test_not_tags_excludes_claimed_notes(vault_tmp: Path):
    obsidian = ObsidianClient(vault_tmp)
    (vault_tmp / "00-Inbox" / "meeting.md").write_text(
        "---\ntags: [meeting]\n---\n\n# Standup\n", encoding="utf-8"
    )
    (vault_tmp / "00-Inbox" / "idea.md").write_text(
        "---\ntags: [idea]\n---\n\n# Spark\n", encoding="utf-8"
    )
    (vault_tmp / "00-Inbox" / "plain.md").write_text("# No frontmatter\n", encoding="utf-8")

    catch_all = _rule(frontmatter_not_tags=["meeting"])
    assert not note_matches_rule(catch_all, "00-Inbox/meeting.md", obsidian)
    assert note_matches_rule(catch_all, "00-Inbox/idea.md", obsidian)
    assert note_matches_rule(catch_all, "00-Inbox/plain.md", obsidian)


def test_not_tags_with_unreadable_note_does_not_fire(vault_tmp: Path):
    obsidian = ObsidianClient(vault_tmp)
    rule = _rule(frontmatter_not_tags=["meeting"])
    assert not note_matches_rule(rule, "00-Inbox/missing.md", obsidian)


def test_bare_path_template_renders_to_relative_path():
    rule = _rule(user_input_template="{{ trigger.file_path }}")
    assert render_user_input(rule, "00-Inbox/idea.md") == "00-Inbox/idea.md"


async def test_dispatch_passes_path_and_respects_exclusion(
    vault_tmp: Path, monkeypatch: pytest.MonkeyPatch
):
    import core.scheduler.triggers as triggers

    rule_file = vault_tmp / ".system" / "trigger-rules" / "inbox-note.yaml"
    rule_file.write_text(
        "id: inbox-note\ntype: vault_watch\nenabled: true\nskill: summarize_note\n"
        "cooldown_seconds: 300\n"
        "match:\n  path_glob: '00-Inbox/*.md'\n  frontmatter:\n    not_tags: [meeting]\n"
        "user_input_template: '{{ trigger.file_path }}'\n",
        encoding="utf-8",
    )
    # Remove the meeting rule from the fixture so only the new rule is active.
    (vault_tmp / ".system" / "trigger-rules" / "inbox.yaml").unlink()

    (vault_tmp / "00-Inbox" / "idea.md").write_text("# Spark\n", encoding="utf-8")
    (vault_tmp / "00-Inbox" / "meeting.md").write_text(
        "---\ntags: [meeting]\n---\n\n# Standup\n", encoding="utf-8"
    )

    calls: list[dict] = []

    async def fake_run_skill(skill, user_input, session_id, **kwargs):
        calls.append({"skill": skill, "user_input": user_input, **kwargs})
        return {"status": "completed"}

    monkeypatch.setattr(triggers, "run_skill", fake_run_skill)
    monkeypatch.setattr(triggers, "obsidian", ObsidianClient(vault_tmp))
    triggers._cooldowns.clear()
    # Fresh-boot regression guard: monotonic starts near zero after a reboot
    # (or in CI); a never-fired rule must still fire even when now < cooldown.
    monkeypatch.setattr(triggers.time, "monotonic", lambda: 5.0)

    await triggers.evaluate_vault_triggers(vault_tmp / "00-Inbox" / "idea.md", vault_tmp)
    await triggers.evaluate_vault_triggers(vault_tmp / "00-Inbox" / "meeting.md", vault_tmp)

    assert len(calls) == 1
    assert calls[0]["skill"] == "summarize_note"
    assert calls[0]["user_input"] == "00-Inbox/idea.md"   # bare path for vault_fs.read_note
    assert calls[0]["trigger_file_path"] == "00-Inbox/idea.md"
