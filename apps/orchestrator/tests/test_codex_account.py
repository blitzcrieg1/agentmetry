"""Codex's account IDs, read from the first line of its session file.

Synthetic values only. The rules that matter: only a session file under Codex's
home is opened, nothing past the first line is read, and a problem leaves the
block absent rather than breaking the hook.
"""

from __future__ import annotations

import base64
import json
import sys
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


#: A token part that decodes to something other than JSON, built here because
#: written out it looks like a key to the secret scan.
_NOT_JSON = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
_AUTH_SECRETS = ("synthetic-access-token", "synthetic-refresh-token", "synthetic-api-key", "Synthetic Name")


def _jwt(claims: dict) -> str:
    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part(claims)}.signature"


def _auth(home: Path, *, mode: str = "chatgpt", email: object = "dev@example.com", extra: dict | None = None) -> Path:
    claims = {"email": email, "name": "Synthetic Name", "sub": "subject-1"}
    body = {
        "OPENAI_API_KEY": "synthetic-api-key",
        "auth_mode": mode,
        "tokens": {
            "id_token": _jwt(claims),
            "access_token": "synthetic-access-token",
            "refresh_token": "synthetic-refresh-token",
            "account_id": "token-account",
        },
        **(extra or {}),
    }
    path = home / "auth.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_only_the_domain_leaves_auth_json(codex_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    _auth(codex_home)
    block = account_for_hook("codex", {})
    assert block == {"domain": "example.com", "source": "codex_auth"}
    text = json.dumps(block)
    for secret in (*_AUTH_SECRETS, "dev@example.com", "subject-1", "token-account"):
        assert secret not in text


def test_the_domain_and_the_ids_arrive_together(codex_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    _auth(codex_home)
    path = _session(codex_home)
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {
        "source": "codex_auth",
        "account_id": "workspace-1",
        "user_id": "user-1",
        "domain": "example.com",
    }


def test_nothing_from_auth_json_reaches_the_stored_event_but_the_domain(
    codex_home: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("AGENTMETRY_SOURCE_APP", "codex")
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    _auth(codex_home)
    payload = hook.map_hook(
        "PostToolUse",
        {"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "git status"}},
    )
    assert payload is not None
    event = build_external_canonical(ExternalIngestBody(**payload).model_dump(exclude_none=True))
    assert event["account"]["domain"] == "example.com"
    for text in (json.dumps(payload), json.dumps(event)):
        for secret in (*_AUTH_SECRETS, "dev@example.com", "subject-1", "token-account"):
            assert secret not in text


def test_an_api_key_sign_in_reports_no_domain(codex_home: Path):
    _auth(codex_home, mode="apikey")
    assert account_for_hook("codex", {}) == {}


def test_it_can_be_turned_off(codex_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_CODEX_AUTH_DOMAIN", "0")
    _auth(codex_home)
    assert account_for_hook("codex", {}) == {}


def test_full_email_still_needs_its_own_opt_in(codex_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", "1")
    _auth(codex_home)
    assert account_for_hook("codex", {})["email"] == "dev@example.com"


@pytest.mark.parametrize(
    "tokens",
    [None, "text", [], {}, {"id_token": None}, {"id_token": 7}, {"id_token": "not-a-jwt"}, {"id_token": "a.%%%.c"}, {"id_token": "a." + _NOT_JSON + ".c"}],
)
def test_a_broken_token_leaves_the_block_absent(codex_home: Path, tokens):
    (codex_home / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt", "tokens": tokens}), encoding="utf-8")
    assert account_for_hook("codex", {}) == {}


@pytest.mark.parametrize("email", [None, 7, "not-an-address", "a@b@c.example", ""])
def test_a_bad_email_claim_leaves_the_block_absent(codex_home: Path, email):
    _auth(codex_home, email=email)
    assert account_for_hook("codex", {}) == {}


@pytest.mark.parametrize("content", ["{not json", "[]", '"text"'])
def test_a_broken_auth_file_leaves_the_block_absent(codex_home: Path, content: str):
    (codex_home / "auth.json").write_text(content, encoding="utf-8")
    assert account_for_hook("codex", {}) == {}


def test_a_huge_auth_file_is_not_read(codex_home: Path):
    _auth(codex_home, extra={"pad": "x" * (256 * 1024 + 10)})
    assert account_for_hook("codex", {}) == {}


def test_codex_joins_the_personal_section_with_its_ids_kept():
    def row(app: str, **kw) -> dict:
        return {
            "source_app": app,
            "action_type": "tool_called",
            "correlation_id": app,
            "timestamp_utc": "2026-11-07T10:00:00+00:00",
            "adapter": f"{app}_hook",
            "domain": "gmail.com",
            **kw,
        }

    view = build_identity_view(
        [
            row("cursor", account_source="hook_payload"),
            row("codex", account_source="codex_auth", account_id="workspace-1", user_id="user-1"),
        ],
        days=7,
    )
    assert len(view["accounts"]) == 1
    account = view["accounts"][0]
    assert account["kind"] == "personal"
    assert account["agents"] == ["codex", "cursor"]
    assert account["account_id"] == "workspace-1"
    assert account["user_id"] == "user-1"


def test_the_ids_come_from_the_session_file(codex_home: Path):
    path = _session(codex_home)
    assert account_for_hook("codex", {"transcript_path": str(path)}) == {
        "source": "session_meta",
        "account_id": "workspace-1",
        "user_id": "user-1",
    }


def test_the_windows_extended_form_of_the_path_is_accepted(codex_home: Path):
    path = _session(codex_home)
    extended = chr(92) * 2 + "?" + chr(92) + str(path)
    assert account_for_hook("codex", {"transcript_path": extended})["account_id"] == "workspace-1"


def test_a_session_with_no_path_is_found_by_its_id(codex_home: Path):
    session = "01a1a857-aaaa-bbbb-cccc-000000000000"
    _session(codex_home, name=f"rollout-2026-11-07T10-00-00-{session}.jsonl")
    assert account_for_hook("codex", {"session_id": session})["account_id"] == "workspace-1"
    assert account_for_hook("codex", {"transcript_path": None, "session_id": session})["user_id"] == "user-1"


def test_a_path_that_fails_falls_back_to_the_id(codex_home: Path, tmp_path: Path):
    session = "01a1a857-aaaa-bbbb-cccc-000000000000"
    _session(codex_home, name=f"rollout-2026-11-07T10-00-00-{session}.jsonl")
    outside = _session(tmp_path / "elsewhere", {"creator_account_id": "not-this-one"})
    block = account_for_hook("codex", {"transcript_path": str(outside), "session_id": session})
    assert block["account_id"] == "workspace-1"


def test_another_session_id_does_not_match(codex_home: Path):
    _session(codex_home, name="rollout-2026-11-07T10-00-00-01a1a857-aaaa.jsonl")
    assert account_for_hook("codex", {"session_id": "01a1a857-bbbb"}) == {}


@pytest.mark.parametrize("session", ["*", "..", "a/b", "a*", "../../etc", "rollout", ""])
def test_a_crafted_session_id_cannot_widen_the_search(codex_home: Path, session: str):
    _session(codex_home, name="rollout-2026-11-07T10-00-00-01a1a857-aaaa.jsonl")
    assert account_for_hook("codex", {"session_id": session}) == {}


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


@pytest.fixture
def antigravity_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if sys.platform == "darwin":
        folder = tmp_path / "Library" / "Application Support" / "Antigravity"
    else:
        folder = tmp_path / "Antigravity"
    folder.mkdir(parents=True)
    return folder / "app_storage.json"


def test_antigravity_reports_the_last_sign_in_as_a_domain(antigravity_storage: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTMETRY_LOG_ACCOUNT_EMAIL", raising=False)
    antigravity_storage.write_text(
        json.dumps({"jetski.onboarding.lastLoginUsername": "dev@example.com", "other": 1}), encoding="utf-8"
    )
    assert account_for_hook("antigravity", {}) == {"domain": "example.com", "source": "local_config"}


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"other": 1}),
        json.dumps({"jetski.onboarding.lastLoginUsername": None}),
        json.dumps({"jetski.onboarding.lastLoginUsername": "not-an-address"}),
        json.dumps({"jetski.onboarding.lastLoginUsername": 7}),
    ],
)
def test_antigravity_problems_leave_the_block_absent(antigravity_storage: Path, content: str):
    antigravity_storage.write_text(content, encoding="utf-8")
    assert account_for_hook("antigravity", {}) == {}


def test_antigravity_with_no_file_or_a_huge_one_is_absent(antigravity_storage: Path):
    assert account_for_hook("antigravity", {}) == {}
    antigravity_storage.write_text(
        json.dumps({"jetski.onboarding.lastLoginUsername": "dev@example.com", "pad": "x" * (1024 * 1024 + 10)}),
        encoding="utf-8",
    )
    assert account_for_hook("antigravity", {}) == {}


def test_a_silent_codex_is_called_out_rather_than_excused():
    row = {
        "source_app": "codex",
        "action_type": "tool_called",
        "correlation_id": "s1",
        "timestamp_utc": "2026-11-07T10:00:00+00:00",
        "adapter": "codex_hook",
    }
    assert build_identity_view([row], days=7)["agents"][0]["state"] == "not_reported"
