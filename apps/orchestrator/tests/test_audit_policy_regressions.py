"""Audit regressions against the shipped manifest. Commands are data, never run."""

from __future__ import annotations

import pytest

from agentmetry.core.audit.tool_policy import evaluate, reset_policy
from agentmetry.core.config import settings


@pytest.fixture(autouse=True)
def shipped_policy(monkeypatch):
    from pathlib import Path

    manifest = Path(__file__).resolve().parents[1] / "agentmetry/policies/tool/manifest.yaml"
    monkeypatch.setattr(settings, "tool_policy_path", manifest)
    reset_policy()
    yield
    reset_policy()


@pytest.mark.parametrize(
    "command,rule",
    [
        ("rm -fr /tmp/synthetic", "block_shell_rm"),
        ("rm -r -f /tmp/synthetic", "block_shell_rm"),
        ("rm --recursive --force /tmp/synthetic", "block_shell_rm"),
        ("rm --force --recursive /tmp/synthetic", "block_shell_rm"),
        ("echo x > .git/hooks/pre-commit", "block_git_hook_persistence"),
        ("printf x >> .git/hooks/pre-push", "block_git_hook_persistence"),
        ("echo '{}' > ~/.claude/settings.json", "block_shell_agent_exec_config_write"),
        ("printf '{}' >> ~/.claude/settings.local.json", "block_shell_agent_exec_config_write"),
        ("echo '{}' > '~/.claude/settings.json'", "block_shell_agent_exec_config_write"),
        ("sed -i 's/a/b/' ~/.claude/settings.json", "block_shell_agent_exec_config_write"),
        (
            "sed --in-place -e 's/a/b/' ~/.claude/settings.json",
            "block_shell_agent_exec_config_write",
        ),
        ("rm ~/.claude/settings.json", "block_shell_agent_exec_config_write"),
        ("mv ~/.claude/settings.json /tmp/synthetic", "block_shell_agent_exec_config_write"),
        ("cp /tmp/synthetic ~/.claude/settings.json", "block_shell_agent_exec_config_write"),
        ("printf '{}' | tee ~/.claude/settings.json", "block_shell_agent_exec_config_write"),
        ("truncate -s 0 ~/.claude/settings.json", "block_shell_agent_exec_config_write"),
        ("echo '{}' > .cursor/hooks.json", "block_shell_agent_exec_config_write"),
        ("echo '{}' > .codex/hooks.json", "block_shell_agent_exec_config_write"),
        (
            "python -c \"from pathlib import Path; Path('.claude/settings.json').write_text('{}')\"",
            "block_shell_agent_exec_config_write",
        ),
        (
            "python -c \"open('.claude/settings.json', 'w').write('{}')\"",
            "block_shell_agent_exec_config_write",
        ),
        (
            "python -c \"from pathlib import Path; Path('.claude/settings.json').open('w')\"",
            "block_shell_agent_exec_config_write",
        ),
    ],
)
def test_regression_denies_reported_policy_bypasses(command, rule):
    verdict = evaluate("Bash", {"tool_input": {"command": command}}, mode="block")
    assert verdict.blocked
    assert verdict.match.rule_id == rule


@pytest.mark.parametrize(
    "command",
    [
        "sudo rm -rf /tmp/synthetic",
        "/bin/rm -rf /tmp/synthetic",
        "sudo rm -fr /tmp/synthetic",
        "/bin/rm -fr /tmp/synthetic",
    ],
)
def test_recursive_delete_keeps_common_prefix_coverage(command):
    verdict = evaluate("Bash", {"command": command}, mode="block")
    assert verdict.blocked and verdict.match.rule_id == "block_shell_rm"


@pytest.mark.parametrize(
    "command",
    [
        "cat ~/.claude/settings.json",
        "head -n 5 ~/.claude/settings.json",
        "stat ~/.claude/settings.json",
        "cp ~/.claude/settings.json /tmp/synthetic-backup.json",
        "printf '%s' '~/.claude/settings.json'",
        "echo 'example: echo x > ~/.claude/settings.json'",
        "git commit -m 'explain .claude/settings.json writes'",
        "sed -n '1p' ~/.claude/settings.json",
        "sed -i 's|~/.claude/settings.json|example|' /tmp/synthetic-doc.txt",
        "python -c \"open('.claude/settings.json').read()\"",
        "python -c \"from pathlib import Path; Path('.claude/settings.json').read_text()\"",
        "python -c \"print('example: open .claude/settings.json for writing')\"",
        "echo x > /tmp/synthetic.json",
        "rm /tmp/notes -- -rf",
        "echo 'rm -r -f /tmp/synthetic'",
        "rm -f /tmp/synthetic",
        "rm -r /tmp/synthetic",
    ],
)
def test_benign_reads_and_mentions_remain_allowed(command):
    assert not evaluate("Bash", {"command": command}, mode="block").blocked


@pytest.mark.parametrize(
    "tool,payload",
    [
        ("shell.run", {"command": "echo '{}' > .claude/settings.json"}),
        ("Bash", {"tool_input": {"command": "echo '{}' > .claude/settings.json"}}),
        ("shell.run", {"toolArgs": '{"command":"echo {} > .claude/settings.json"}'}),
        (
            "antigravity.run_command",
            {"toolCall": {"args": {"CommandLine": "echo '{}' > .claude/settings.json"}}},
        ),
    ],
)
def test_shell_write_policy_reads_supported_hook_payload_containers(tool, payload):
    assert evaluate(tool, payload, mode="block").blocked


def test_log_mode_matches_without_claiming_a_hook_block():
    verdict = evaluate("Bash", {"command": "echo '{}' > .claude/settings.json"}, mode="log")
    assert verdict.matched and verdict.blocked
    assert verdict.mode == "log"  # Enforcement is the pre-hook's responsibility.


def test_disabling_policy_keeps_it_disabled():
    assert not evaluate("Bash", {"command": "rm -fr /tmp/synthetic"}, mode="disable").matched


def test_unsupported_expansion_is_not_claimed_as_covered():
    # No variable/cwd resolution or interpreter execution is performed.
    assert not evaluate("Bash", {"command": 'echo x > "$CONFIG"'}, mode="block").blocked


def test_invalid_shell_and_python_text_do_not_crash():
    from agentmetry.core.audit.tool_policy.shell_writes import literal_write_targets

    assert literal_write_targets("echo 'unterminated") == []
    assert literal_write_targets('python -c "not valid python !"') == []
