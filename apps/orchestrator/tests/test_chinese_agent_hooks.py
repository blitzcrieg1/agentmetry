"""Tests for Qwen Code and Kimi Code hook mappers + bootstrap."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from agentmetry_ingest import map_kimi_hook, map_qwen_hook  # noqa: E402

from core.audit.external import build_external_canonical
from core.audit.hook_bootstrap import (
    FAMILY_HOOK_EVENTS,
    install_kimi_global_hooks,
    install_qwen_global_hooks,
    kimi_hooks_toml_block,
    merge_family_hooks,
    merge_kimi_hooks_toml,
)


def _hook_payload(**overrides) -> dict:
    base = {
        "session_id": "sess-qwen-1",
        "tool_name": "run_shell_command",
        "tool_input": {"command": "pytest -q"},
        "hook_event_name": "PostToolUse",
    }
    base.update(overrides)
    return base


def test_qwen_post_tool_use_maps_source():
    payload = map_qwen_hook("PostToolUse", _hook_payload())
    assert payload is not None
    assert payload["source_app"] == "qwen"
    assert payload["adapter"] == "qwen_hook"
    assert payload["tool"]["server"] == "qwen"


def test_kimi_pre_tool_use_maps_source():
    payload = map_kimi_hook("PreToolUse", _hook_payload(hook_event_name="PreToolUse"))
    assert payload is not None
    assert payload["source_app"] == "kimi"
    assert payload["event_type"] == "approval_request"


def test_qwen_post_tool_use_failure():
    payload = map_qwen_hook(
        "PostToolUseFailure",
        _hook_payload(hook_event_name="PostToolUseFailure", error="denied"),
    )
    assert payload["event_type"] == "tool_failed"
    assert payload["source_app"] == "qwen"


def test_build_external_canonical_preserves_qwen_and_crewai():
    qwen = build_external_canonical({
        "source_app": "qwen",
        "event_type": "tool_called",
        "correlation_id": "q-1",
        "tool": {"qualified": "run_shell_command", "server": "qwen", "input_hash": "a" * 64},
    })
    assert qwen["source"]["app"] == "qwen"

    crew = build_external_canonical({
        "source_app": "crewai",
        "event_type": "tool_called",
        "correlation_id": "c-1",
        "tool": {"qualified": "crewai.run", "server": "crewai", "input_hash": "b" * 64},
    })
    assert crew["source"]["app"] == "crewai"
    assert crew["agent"]["name"] == "crewai"


def test_merge_family_hooks_is_idempotent(tmp_path: Path):
    ingest = tmp_path / "agentmetry_ingest.py"
    ingest.write_text("# stub", encoding="utf-8")
    settings: dict = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
    merge_family_hooks(
        settings,
        events=("PreToolUse",),
        source_app="qwen",
        python="/py",
        ingest=ingest,
    )
    merge_family_hooks(
        settings,
        events=("PreToolUse",),
        source_app="qwen",
        python="/py",
        ingest=ingest,
    )
    ours = [g for g in settings["hooks"]["PreToolUse"] if "qwen hook" in str(g)]
    assert len(ours) == 1


def test_install_qwen_global_hooks(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    ingest = repo / "scripts" / "agentmetry_ingest.py"
    ingest.parent.mkdir(parents=True)
    ingest.write_text("# stub", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setattr("core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_qwen_global_hooks(repo_root=repo, python="/usr/bin/python3")
    assert path == home / ".qwen" / "settings.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "PreToolUse" in written["hooks"]
    assert "qwen hook PreToolUse" in str(written["hooks"]["PreToolUse"])


def test_merge_kimi_hooks_toml_replaces_managed_block(tmp_path: Path):
    ingest = tmp_path / "agentmetry_ingest.py"
    ingest.write_text("# stub", encoding="utf-8")
    block = kimi_hooks_toml_block(python="/py", ingest=ingest)
    merged = merge_kimi_hooks_toml("default_model = \"kimi\"\n", block)
    assert "agentmetry hooks begin" in merged
    assert "default_model" in merged
    assert all(event in merged for event in FAMILY_HOOK_EVENTS)


def test_install_kimi_global_hooks(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    ingest = repo / "scripts" / "agentmetry_ingest.py"
    ingest.parent.mkdir(parents=True)
    ingest.write_text("# stub", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setattr("core.audit.hook_bootstrap.Path.home", lambda: home)

    path = install_kimi_global_hooks(repo_root=repo, python="/usr/bin/python3")
    assert path == home / ".kimi-code" / "config.toml"
    text = path.read_text(encoding="utf-8")
    assert "kimi hook PreToolUse" in text
    assert "agentmetry hooks end" in text
