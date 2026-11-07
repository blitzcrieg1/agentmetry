"""Codex's account IDs, read from the first line of its session file.

Synthetic values only. The rules that matter: only a session file under Codex's
home is opened, nothing past the first line is read, and a problem leaves the
block absent rather than breaking the hook.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentmetry.api.routes.audit import ExternalIngestBody
from agentmetry.core.account import account_for_hook, account_from_claim
from agentmetry.core.audit.adapters.chronicle import canonical_to_udm
from agentmetry.core.audit.adapters.ecs import canonical_to_ecs
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.identity_view import build_identity_view
from agentmetry.hooks import ingest as hook


def _session(home: Path, meta: dict | None = None, name: str = "rollout-1.jsonl") -> Path:
    folder = home / "sessions" / "2026" / "11" / "07"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"creator_account_id": "workspace-1", "creator_user_id": "user-1", "id": "s1"}
    record = {"type": "session_meta", "payload": payload if meta is None else meta}
    path = folder / name
    path.write_text(json.dumps(record) + "\n" + json.dumps({"type": "other"}) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def test_the_ids_come_from_the_session_file(codex_home: Path):
    path = _session(codex_home)
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {
        "source": "session_meta",
        "account_id": "workspace-1",
        "user_id": "user-1",
    }


def test_a_file_outside_codex_home_is_not_opened(codex_home: Path, tmp_path: Path):
    outside = _session(tmp_path / "elsewhere")
    assert account_for_hook("codex", {"transcript_path": str(outside)}) == {}


def test_a_traversal_out_of_codex_home_is_not_opened(codex_home: Path, tmp_path: Path):
    outside = _session(tmp_path / "elsewhere")
    crafted = codex_home / "sessions" / ".." / ".." / "elsewhere" / outside.relative_to(tmp_path / "elsewhere")
    assert account_for_hook("codex", {"transcript_path": str(crafted)}) == {}


def test_only_jsonl_files_are_considered(codex_home: Path):
    auth = codex_home / "auth.json"
    auth.write_text(json.dumps({"type": "session_meta", "payload": {"creator_account_id": "x"}}), encoding="utf-8")
    assert account_for_hook("codex", {"transcript_path": str(auth)}) == {}


@pytest.mark.parametrize("value", [None, 7, "", [], "missing.jsonl"])
def test_a_bad_path_leaves_the_block_absent(codex_home: Path, value):
    assert account_for_hook("codex", {"transcript_path": value}) == {}
    assert account_for_hook("codex", {}) == {}


def test_a_first_line_that_is_not_session_meta_is_ignored(codex_home: Path):
    path = codex_home / "sessions" / "x.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"type":"other","payload":{"creator_account_id":"workspace-1"}}\n', encoding="utf-8")
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {}


def test_a_later_line_is_not_read(codex_home: Path):
    path = codex_home / "sessions" / "x.jsonl"
    path.parent.mkdir(parents=True)
    later = json.dumps({"type": "session_meta", "payload": {"creator_account_id": "workspace-9"}})
    path.write_text('{"type":"other"}\n' + later + "\n", encoding="utf-8")
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {}


def test_broken_json_leaves_the_block_absent(codex_home: Path):
    path = codex_home / "sessions" / "x.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{not json\n", encoding="utf-8")
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {}


def test_an_oversized_first_line_leaves_the_block_absent(codex_home: Path):
    path = _session(codex_home, {"creator_account_id": "workspace-1", "pad": "x" * (1024 * 1024 + 10)})
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {}


@pytest.mark.parametrize(
    "bad",
    ["has space", "a" * 129, "line\nbreak", "semi;colon", "dev@example.com", "../../etc", 7, None, ["x"]],
)
def test_an_id_of_the_wrong_shape_is_dropped(codex_home: Path, bad):
    path = _session(codex_home, {"creator_account_id": bad, "creator_user_id": "user-1"})
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {
        "source": "session_meta",
        "user_id": "user-1",
    }


def test_the_ids_survive_the_real_mapper_and_ingest_model(codex_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "codex")
    path = _session(codex_home)
    payload = hook.map_hook(
        "PostToolUse",
        {
            "session_id": "codex-account",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "transcript_path": str(path),
            "model": "synthetic-model",
        },
    )
    assert payload is not None
    kept = ExternalIngestBody(**payload).model_dump(exclude_none=True)
    event = build_external_canonical(kept)
    assert event["account"] == {"source": "session_meta", "account_id": "workspace-1", "user_id": "user-1"}
    assert event["model"]["id"] == "synthetic-model"
    # The spool replay skips the HTTP model and must record the same thing.
    assert build_external_canonical(payload)["account"] == event["account"]


def test_the_ids_are_bounded_on_the_recorder_side_too():
    account = account_from_claim("", "session_meta", account_id="a b", user_id="u" * 500)
    assert account == {}
    both = account_from_claim("example.com", "otel", account_id="workspace-1")
    assert both == {"source": "otel", "account_id": "workspace-1", "domain": "example.com"}


def test_sinks_carry_the_ids_without_calling_them_identity():
    event = build_external_canonical(
        {
            "source_app": "codex",
            "event_type": "tool_called",
            "correlation_id": "c1",
            "tool": {"qualified": "shell.run", "command": "git status"},
            "account": {"source": "session_meta", "account_id": "workspace-1", "user_id": "user-1"},
        }
    )
    ecs = canonical_to_ecs(event)
    assert ecs["agentmetry"]["account"]["account_id"] == "workspace-1"
    assert "workspace-1" not in json.dumps(ecs.get("user", {}))
    udm = canonical_to_udm(event)
    labels = {item["key"]: item["value"] for item in udm["additional"]["labels"]}
    assert labels["agent_account_id"] == "workspace-1"
    assert labels["agent_account_user_id"] == "user-1"


def test_the_identity_view_shows_an_id_only_account():
    row = {
        "source_app": "codex",
        "action_type": "tool_called",
        "action_outcome": "success",
        "correlation_id": "s1",
        "timestamp_utc": "2026-11-07T10:00:00+00:00",
        "adapter": "codex_hook",
        "account_id": "workspace-1",
        "user_id": "user-1",
        "account_source": "session_meta",
    }
    view = build_identity_view([row], days=7)
    assert view["accounts"][0]["account_id"] == "workspace-1"
    assert view["accounts"][0]["user_id"] == "user-1"
    assert view["accounts"][0]["domain"] == ""
    assert view["agents"][0]["state"] == "reported"
    assert view["sessions_without_account"] == 0


def test_a_silent_codex_is_called_out_rather_than_excused():
    row = {
        "source_app": "codex",
        "action_type": "tool_called",
        "correlation_id": "s1",
        "timestamp_utc": "2026-11-07T10:00:00+00:00",
        "adapter": "codex_hook",
    }
    assert build_identity_view([row], days=7)["agents"][0]["state"] == "not_reported"
