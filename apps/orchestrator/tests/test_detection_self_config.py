"""Tests for the edits_self_config trait (#317).

An agent that rewrites the files governing itself — its settings, its hook
definitions — is changing its own guardrails. The trait is the signal; these
tests pin both halves of it: the writes that must earn it (Write tool, patch
bodies, and shell writes aimed at the path) and the lookalikes that must
not (reads, other tools' settings files, prose about the path).
"""

from __future__ import annotations

from agentmetry.core.audit.detection.traits import (
    KNOWN_TRAITS,
    classify_command,
    classify_tool_call,
)
from agentmetry.core.audit.mitre import get_mitre_mapping


# --- the Write tool ----------------------------------------------------------


def test_the_trait_is_in_the_vocabulary():
    assert "edits_self_config" in KNOWN_TRAITS


def test_write_to_claude_settings_fires():
    assert classify_tool_call("Write", "/home/operator/.claude/settings.json") == ["edits_self_config"]
    assert classify_tool_call("Edit", "~/.claude/settings.local.json") == ["edits_self_config"]
    assert classify_tool_call("Write", "C:\\Users\\operator\\.claude\\settings.json") == ["edits_self_config"]


def test_write_to_hook_files_and_other_agents_fires():
    assert classify_tool_call("Write", "~/.claude/hooks/guard.py") == ["edits_self_config"]
    assert classify_tool_call("Write", "~/.claude.json") == ["edits_self_config"]
    assert classify_tool_call("Write", "~/.cursor/hooks.json") == ["edits_self_config"]
    assert classify_tool_call("Write", "~/.codex/hooks.json") == ["edits_self_config"]
    assert classify_tool_call("Write", "~/.codex/config.toml") == ["edits_self_config"]


def test_project_local_agent_config_counts():
    """Claude Code reads `.claude/settings.json` from the project too."""
    assert classify_tool_call("Write", "/srv/repo/.claude/settings.json") == ["edits_self_config"]


def test_patch_body_naming_the_path_fires():
    body = "*** Begin Patch\n*** Update File: ~/.claude/settings.json\n@@\n+{}\n*** End Patch"
    assert classify_tool_call("apply_patch", body) == ["edits_self_config"]


def test_write_to_other_settings_stays_quiet():
    assert classify_tool_call("Write", "/srv/repo/.vscode/settings.json") == []
    assert classify_tool_call("Write", "/srv/repo/src/settings.json") == []
    assert classify_tool_call("Write", "~/.config/myapp/settings.json") == []
    assert classify_tool_call("Write", "~/.claude/projects/session-notes.md") == []
    assert classify_tool_call("Write", "~/.claude/settings.json.bak") == []


def test_reading_the_config_is_not_editing_it():
    assert "edits_self_config" not in classify_tool_call("Read", "~/.claude/settings.json")


# --- shell writes --------------------------------------------------------------


def test_redirect_into_the_config_fires():
    assert "edits_self_config" in classify_command("cat payload.json > ~/.claude/settings.json")
    assert "edits_self_config" in classify_command("echo '{}' >> /home/operator/.codex/config.toml")


def test_tee_in_place_sed_dd_and_copy_destination_fire():
    assert "edits_self_config" in classify_command("tee ~/.cursor/hooks.json < hooks.json")
    assert "edits_self_config" in classify_command("sed -i 's/\"a\"/\"b\"/' ~/.claude/settings.json")
    assert "edits_self_config" in classify_command("dd if=/tmp/x of=$HOME/.claude/settings.json")
    assert "edits_self_config" in classify_command("cp /tmp/evil.json ~/.claude/settings.json")
    assert "edits_self_config" in classify_command("mv old.toml ~/.codex/config.toml")


def test_reading_the_config_by_command_stays_quiet():
    assert "edits_self_config" not in classify_command("cat ~/.claude/settings.json")
    assert "edits_self_config" not in classify_command("grep -n hooks ~/.claude/settings.json")
    assert "edits_self_config" not in classify_command("cp ~/.claude/settings.json /tmp/backup.json")


def test_prose_about_the_path_stays_quiet():
    """Single-quoted text is something written, not a file being written."""
    assert "edits_self_config" not in classify_command("echo 'edit ~/.claude/settings.json by hand'")


# --- the MITRE mapper agrees -----------------------------------------------------


def test_mapper_upgrades_a_self_config_write_to_t1562():
    mapping = get_mitre_mapping("Write", {"file_path": "~/.claude/settings.json"})
    assert mapping is not None
    assert mapping["technique_id"] == "T1562"
    assert mapping["tactic_id"] == "TA0005"


def test_mapper_leaves_an_ordinary_write_alone():
    mapping = get_mitre_mapping("Write", {"file_path": "src/app.py"})
    assert mapping is not None
    assert mapping["technique_id"] != "T1562"


def test_mapper_ignores_the_path_in_written_content():
    """Prose in the file body naming the path is not a write to that path."""
    mapping = get_mitre_mapping(
        "Write",
        {"file_path": "docs/setup.md", "content": "edit ~/.claude/settings.json to add the hook"},
    )
    assert mapping is not None
    assert mapping["technique_id"] != "T1562"
