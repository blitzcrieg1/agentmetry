"""Agent env override DLP — CVE-2025-59536 / CVE-2026-21852 env half."""

from __future__ import annotations

import json
import re

import pytest

from core.audit.dlp import scan
from core.audit.dlp.loader import load_dlp_rules
from core.audit.dlp.scanner import reset_rules
from core.config import settings

RULE_ID = "agent_env_override"


@pytest.fixture(autouse=True)
def _reset_dlp_cache():
    reset_rules()
    yield
    reset_rules()


def _pattern() -> str:
    for rule in load_dlp_rules(settings.dlp_rules_path):
        if rule.id == RULE_ID:
            return rule.pattern
    raise AssertionError(f"{RULE_ID} missing from manifest")


def _rule_ids(verdict) -> list[str]:
    return [m.rule_id for m in (verdict.matches or [])]


def test_pattern_matches_shell_and_json_forms():
    rx = re.compile(_pattern())
    assert rx.search("ANTHROPIC_BASE_URL=https://evil.tld")
    assert rx.search('export HTTPS_PROXY=http://1.2.3.4:8080')
    blob = json.dumps({"NODE_OPTIONS": "--require ./x.js"})
    assert rx.search(blob)


@pytest.mark.parametrize(
    "label,payload",
    [
        ("anthropic base url", {"tool_input": {"content": "ANTHROPIC_BASE_URL=https://evil.tld"}}),
        ("https proxy export", {"command": "export HTTPS_PROXY=http://1.2.3.4:8080"}),
        ("json node options", {"tool_input": {"NODE_OPTIONS": "--require ./x.js"}}),
        ("ld preload", {"tool_input": {"content": "LD_PRELOAD=/tmp/evil.so"}}),
        ("openai base", {"tool_input": {"content": "OPENAI_API_BASE: http://attacker"}}),
    ],
)
def test_env_override_detected(label, payload):
    verdict = scan("Edit", payload, mode="log")
    assert verdict.matched, f"missed: {label}"
    assert RULE_ID in _rule_ids(verdict)


@pytest.mark.parametrize(
    "label,payload",
    [
        ("prose model name", {"tool_input": {"content": "ANTHROPIC_MODEL is opus"}}),
        ("docs mention", {"tool_input": {"content": "Set HTTP_PROXY in your shell profile docs."}}),
        ("normal python", {"tool_input": {"content": "def main():\n    return 1"}}),
    ],
)
def test_env_override_benign(label, payload):
    verdict = scan("Edit", payload, mode="log")
    assert RULE_ID not in _rule_ids(verdict), f"false positive: {label}"
