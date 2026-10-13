"""`agentmetry posture`: agent settings that take a human or a hook out of the loop.

Every setting checked here is from the vendor's own settings reference (see the
module docstring). These tests pin two things: each documented risky value is
reported, and the safe or neutral value is not, because a posture report that
flags ordinary configuration trains people to ignore it.

Every test runs against a fake home: nothing reads the real machine's settings.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agentmetry.core.audit import posture_event
from agentmetry.core.diagnostics import posture as pm


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(pm.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(pm, "_claude_managed_settings", lambda: tmp_path / "managed" / "managed-settings.json")
    monkeypatch.setattr(pm, "vscode_user_settings", lambda: [tmp_path / "Code" / "User" / "settings.json"])
    for var in ("CODEX_HOME", "COPILOT_HOME"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _settings(f: pm.Posture) -> set[tuple[str, str, str, str]]:
    return {(x.agent, x.scope, x.setting, x.severity) for x in f.findings}


def test_a_clean_machine_reports_nothing_but_says_what_it_did_not_check(home):
    p = pm.collect()
    assert p.findings == []
    assert any("not checked: cursor" in line for line in pm.summary_lines(p))


# --- Claude Code ---------------------------------------------------------------


def test_claude_bypass_mode_and_a_shell_wildcard_are_high(home):
    _write(home / ".claude" / "settings.json", json.dumps({
        "permissions": {"defaultMode": "bypassPermissions", "allow": ["Bash", "Read(*)"]},
    }))
    s = _settings(pm.collect())
    assert ("claude", "user", "permissions.defaultMode", "high") in s
    assert ("claude", "user", "permissions.allow", "high") in s
    assert len([x for x in s if x[2] == "permissions.allow"]) == 1, "Read(*) is not a shell wildcard"


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "plan", "dontAsk"])
def test_ordinary_modes_are_not_findings(home, mode):
    _write(home / ".claude" / "settings.json", json.dumps({"permissions": {"defaultMode": mode}}))
    assert pm.collect().findings == []


def test_bypass_from_project_settings_is_medium_because_newer_claude_ignores_it(home, tmp_path):
    project = tmp_path / "repo"
    _write(project / ".claude" / "settings.json", json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    s = _settings(pm.collect(project))
    assert ("claude", "project", "permissions.defaultMode", "medium") in s


def test_a_managed_ban_on_bypass_downgrades_it(home):
    _write(home / "managed" / "managed-settings.json", json.dumps({
        "permissions": {"disableBypassPermissionsMode": "disable"},
    }))
    _write(home / ".claude" / "settings.json", json.dumps({
        "permissions": {"defaultMode": "bypassPermissions"}, "skipDangerousModePermissionPrompt": True,
    }))
    s = _settings(pm.collect())
    assert ("claude", "user", "permissions.defaultMode", "low") in s
    assert not any(x[2] == "skipDangerousModePermissionPrompt" for x in s)


def test_claude_hooks_off_and_blanket_mcp_approval(home):
    _write(home / ".claude" / "settings.json", json.dumps({
        "disableAllHooks": True, "enableAllProjectMcpServers": True,
    }))
    s = _settings(pm.collect())
    assert ("claude", "user", "disableAllHooks", "high") in s
    assert ("claude", "user", "enableAllProjectMcpServers", "medium") in s


# --- Codex ----------------------------------------------------------------------


def test_codex_never_asking_and_no_sandbox_are_both_high(home):
    _write(home / ".codex" / "config.toml",
           'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n[features]\nhooks = false\n')
    s = _settings(pm.collect())
    assert ("codex", "user", "approval_policy", "high") in s
    assert ("codex", "user", "sandbox_mode", "high") in s
    assert ("codex", "user", "features.hooks", "high") in s


def test_codex_defaults_are_not_findings(home):
    _write(home / ".codex" / "config.toml", 'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n')
    assert pm.collect().findings == []


def test_a_codex_profile_file_is_read_too(home):
    _write(home / ".codex" / "yolo.config.toml", 'approval_policy = "never"\n')
    assert ("codex", "profile:yolo", "approval_policy", "high") in _settings(pm.collect())


# --- VS Code / Copilot -----------------------------------------------------------


def test_vscode_settings_with_comments_and_trailing_commas_are_read(home):
    """VS Code settings are JSONC. A strict parser would call this unreadable
    and report a clean machine."""
    _write(home / "Code" / "User" / "settings.json", """{
      // the YOLO switch
      "chat.tools.global.autoApprove": true,
      /* hooks */ "chat.useHooks": false,
      "chat.tools.terminal.autoApprove": {"/.*/": true, "ls": true,},
      "url": "https://example.com/not//a/comment",
    }""")
    p = pm.collect()
    s = _settings(p)
    assert ("copilot", "user", "chat.tools.global.autoApprove", "high") in s
    assert ("copilot", "user", "chat.useHooks", "high") in s
    assert [x.value for x in p.findings if x.setting == "chat.tools.terminal.autoApprove"] == ["/.*/"]
    assert p.unreadable == []


def test_vscode_session_default_autopilot_is_high(home):
    _write(home / "Code" / "User" / "settings.json", '{"chat.permissions.default": "autopilot"}')
    assert ("copilot", "user", "chat.permissions.default", "high") in _settings(pm.collect())


def test_copilot_cli_hooks_off(home):
    _write(home / ".copilot" / "settings.json", '{"disableAllHooks": true}')
    assert ("copilot", "user", "disableAllHooks", "high") in _settings(pm.collect())


# --- robustness and the wire ----------------------------------------------------


def test_an_unparseable_file_is_reported_not_raised(home):
    _write(home / ".claude" / "settings.json", "{not json")
    p = pm.collect()
    assert p.unreadable and p.findings == []


def test_the_wire_form_carries_no_path(home):
    _write(home / ".claude" / "settings.json", json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    event = posture_event.build_posture_event("2026-10-13T00:00:00Z", pm.collect(), outcome="snapshot")
    blob = json.dumps(event)
    assert str(home) not in blob and "settings.json" not in blob
    assert event["action"]["type"] == "posture"
    assert event["posture"]["counts"]["high"] == 1


def test_the_digest_moves_only_when_findings_do(home):
    path = home / ".claude" / "settings.json"
    _write(path, json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    first = pm.collect().digest()
    assert pm.collect().digest() == first
    _write(path, json.dumps({"permissions": {"defaultMode": "default"}}))
    assert pm.collect().digest() != first


def test_the_event_is_off_unless_the_operator_turns_it_on(monkeypatch):
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "posture_enabled", False, raising=False)
    assert asyncio.run(posture_event.maybe_emit_posture(posture_event.PostureState())) is None


def test_due_snapshots_then_reports_change_then_stays_quiet():
    state = posture_event.PostureState()
    assert posture_event.due(state, "a", 0.0) == "snapshot"
    state.digest, state.emitted_at = "a", 0.0
    assert posture_event.due(state, "a", 10.0) is None
    assert posture_event.due(state, "b", 10.0) == "changed"
    assert posture_event.due(state, "a", posture_event.SNAPSHOT_SECONDS + 1) == "snapshot"


def test_the_cli_exits_0_with_findings_and_1_only_when_strict(home, capsys):
    from agentmetry.cli import main

    _write(home / ".claude" / "settings.json", json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    assert main(["posture"]) == 0
    assert main(["posture", "--strict"]) == 1
    assert main(["posture", "--json"]) == 0
    out = capsys.readouterr().out
    assert '"setting": "permissions.defaultMode"' in out
