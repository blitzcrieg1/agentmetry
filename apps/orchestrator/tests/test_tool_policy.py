"""Tests for YAML tool allow/deny policy (hook-boundary enforcement)."""

from pathlib import Path

import pytest

from core.audit.tool_policy import evaluate, reset_policy
from core.config import settings


@pytest.fixture(autouse=True)
def _reset_tool_policy_cache():
    reset_policy()
    yield
    reset_policy()


def _write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_deny_rm_rf_on_bash(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "tool.yaml",
        """
version: "1.0"
default: allow
rules:
  - id: block_shell_rm
    action: deny
    tools: ["Bash", "shell.run"]
    command_pattern: "(?i)\\\\brm\\\\s+-rf\\\\b"
""",
    )
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    monkeypatch.setattr(settings, "tool_policy_mode", "block")

    verdict = evaluate("Bash", {"command": "rm -rf /tmp/foo"})
    assert verdict.matched is True
    assert verdict.blocked is True
    assert verdict.match.rule_id == "block_shell_rm"


def test_allow_read_when_default_deny(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "tool.yaml",
        """
version: "1.0"
default: deny
rules:
  - id: read_only
    action: allow
    tools: ["Read", "Glob"]
""",
    )
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    monkeypatch.setattr(settings, "tool_policy_mode", "block")

    allowed = evaluate("Read", {"path": "/etc/passwd"})
    assert allowed.matched is True
    assert allowed.blocked is False

    denied = evaluate("Bash", {"command": "ls"})
    assert denied.matched is True
    assert denied.blocked is True
    assert denied.match.rule_id == "default_deny"


def test_log_mode_records_but_does_not_block(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "tool.yaml",
        """
version: "1.0"
default: allow
rules:
  - id: block_kubectl
    action: deny
    tools: ["kubectl.exec"]
""",
    )
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    monkeypatch.setattr(settings, "tool_policy_mode", "log")

    verdict = evaluate("kubectl.exec", {"pod": "web-0"})
    assert verdict.matched is True
    assert verdict.blocked is True
    assert verdict.mode == "log"


def test_disable_mode_is_noop(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "tool.yaml",
        """
version: "1.0"
default: allow
rules:
  - id: block_all
    action: deny
    tools: ["*"]
""",
    )
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    monkeypatch.setattr(settings, "tool_policy_mode", "disable")

    verdict = evaluate("Bash", {"command": "rm -rf /"})
    assert verdict.matched is False
    assert verdict.blocked is False


def test_command_pattern_required_for_shell_deny(tmp_path, monkeypatch):
    manifest = _write_manifest(
        tmp_path / "tool.yaml",
        """
version: "1.0"
default: allow
rules:
  - id: block_shell_rm
    action: deny
    tools: ["Bash"]
    command_pattern: "(?i)\\\\brm\\\\s+-rf\\\\b"
""",
    )
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    monkeypatch.setattr(settings, "tool_policy_mode", "block")

    safe = evaluate("Bash", {"command": "ls -la"})
    assert safe.matched is False
    assert safe.blocked is False


def test_tool_policy_survives_canonicalization():
    from core.audit.external import build_external_canonical

    event = build_external_canonical(
        {
            "source_app": "cursor",
            "event_type": "tool_called",
            "correlation_id": "sess-tp",
            "tool": {"qualified": "Bash", "arguments": {"command": "rm -rf /"}},
            "tool_policy": {
                "rule_id": "block_shell_rm",
                "action": "deny",
                "mode": "log",
                "blocked": True,
            },
        }
    )
    assert event["tool_policy"]["rule_id"] == "block_shell_rm"
    assert event["tool_policy"]["blocked"] is True
