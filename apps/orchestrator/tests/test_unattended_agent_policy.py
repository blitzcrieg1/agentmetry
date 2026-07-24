"""Unattended-agent coverage — Hermes class (Hunt.io, July 2026).

An operator ran Nous Research's Hermes assistant against Thailand's Ministry of
Finance with YOLO mode enabled via its documented CLI flag, unattended. The flag
is the behaviour worth denying, not the vendor, so the policy matches the flag on
any binary and the agent-name rule is only a second net.

Tests run against the REAL shipped manifests, not fixtures.
"""

from __future__ import annotations

import pytest

from core.audit.dlp import scan as dlp_scan
from core.audit.dlp.scanner import reset_rules
from core.audit.tool_policy import evaluate as tool_policy_eval


@pytest.fixture(autouse=True)
def _fresh_rules():
    reset_rules()
    yield
    reset_rules()


def _verdict(command: str):
    return tool_policy_eval("Bash", {"command": command}, server="shell", mode="block")


@pytest.mark.parametrize("command", [
    "hermes --yolo --task 'enumerate hosts'",
    "aider --yolo",
    "openhands --auto-approve",
    "some-new-agent-cli --dangerously-skip-permissions",
    "runner --unattended --target 10.0.0.5",
    "goose session --no-confirm",
])
def test_unattended_flags_are_denied_on_any_binary(command):
    verdict = _verdict(command)
    assert verdict.matched and verdict.blocked, f"should deny: {command}"


@pytest.mark.parametrize("command", [
    "git status",
    "npm run build",
    "pytest -q",
    "docker compose up -d",
])
def test_ordinary_commands_are_not_denied(command):
    assert not _verdict(command).blocked, f"false positive on: {command}"


def test_agentmetry_own_kimi_ingest_pipeline_is_not_blocked():
    """The documented Sprint C capture workflow must not trip its own policy."""
    command = (
        'kimi -p "refactor this" --output-format stream-json '
        "| python scripts/agentmetry_ingest.py kimi stream-json"
    )
    assert not _verdict(command).blocked, "Agentmetry must not deny its own ingest path"


def test_hermes_named_agent_still_caught_by_cli_rule():
    verdict = _verdict("hermes --print --prompt 'scan the subnet'")
    assert verdict.matched and verdict.blocked


def test_hermes_results_directory_is_a_dlp_ioc():
    verdict = dlp_scan("Bash", {"command": "tar czf loot.tgz /var/www/hermes-results/"})
    assert verdict.matched
    assert "agent_result_dump_dir" in [m.rule_id for m in verdict.matches]


# AWS's published, non-functional example secret key (40 chars including the
# slashes) — the same class of documented sample as AKIAIOSFODNN7EXAMPLE.
_AWS_EXAMPLE_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # gitleaks:allow


@pytest.mark.parametrize("command", [
    "git checkout 1f0c2b9a4e7d3c5f8a1b2c3d4e5f6a7b8c9d0e1f",
    "git log --format=%H 5553ab7e1f0c2b9a4e7d3c5f8a1b2c3d4e5f6a7b",
    "git diff 582085b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7 HEAD",
])
def test_git_shas_are_not_aws_secrets(command):
    """Regression: the bare 40-char pattern matched every commit SHA, so block
    mode denied ordinary git commands."""
    verdict = dlp_scan("Bash", {"command": command})
    assert "aws_secret_key" not in [m.rule_id for m in (verdict.matches or [])]


@pytest.mark.parametrize("command", [
    f"export AWS_SECRET_ACCESS_KEY={_AWS_EXAMPLE_SECRET}",
    f'aws_secret_access_key: "{_AWS_EXAMPLE_SECRET}"',
    f'{{"secretAccessKey": "{_AWS_EXAMPLE_SECRET}"}}',
])
def test_real_aws_secret_assignments_still_match(command):
    verdict = dlp_scan("Bash", {"command": command})
    assert "aws_secret_key" in [m.rule_id for m in (verdict.matches or [])], command
