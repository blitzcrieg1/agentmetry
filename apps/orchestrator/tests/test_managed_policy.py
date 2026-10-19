"""Managed policy wins, and a user-writable file does not count as managed.

Solo installs have no managed file. These tests pin that, and pin the
downgrade a fleet file exists to stop: a developer (or their agent) setting
AGENTMETRY_DLP_MODE=disable under a lock of block.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from agentmetry.core import managed_policy as mp
from agentmetry.core.audit import policy_settings as ps
from agentmetry.core.config import settings


@pytest.fixture
def trusted(monkeypatch):
    """Treat every candidate as root-owned. The refusal tests do not use this."""
    monkeypatch.setattr(mp, "assess_trust", lambda path: mp.Trust(True, "test double"))
    mp.clear_cache()
    yield
    mp.clear_cache()


def _candidates(monkeypatch, paths: list[Path]) -> None:
    monkeypatch.setattr(mp, "platform_managed_candidates", lambda: list(paths))
    monkeypatch.setattr(mp, "read_registry_policy", lambda: None)
    mp.clear_cache()


def test_no_managed_file_locks_nothing(monkeypatch):
    _candidates(monkeypatch, [])
    layers = mp.load_policy()
    assert layers.locked == {}
    assert layers.rejected == []


def test_a_user_writable_file_is_refused(monkeypatch, tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text("schema: 1\ndlp_mode: disable\nauth_disabled: true\n", encoding="utf-8")
    _candidates(monkeypatch, [policy])
    layers = mp.load_policy()
    assert layers.locked == {}
    assert layers.rejected
    assert "dlp_mode" not in layers.locked


def test_posix_chain_rejects_a_writable_parent():
    verdict = mp.judge_posix_chain([
        ("/", 0, 0o755, False),
        ("/etc", 0, 0o755, False),
        ("/etc/agentmetry", 0, 0o777, False),
        ("/etc/agentmetry/policy.yaml", 0, 0o644, False),
    ])
    assert verdict.trusted is False
    assert "writable" in verdict.reason


def test_posix_chain_rejects_a_symlink_and_a_non_root_owner():
    link = mp.judge_posix_chain([
        ("/", 0, 0o755, False),
        ("/etc/agentmetry/policy.yaml", 0, 0o644, True),
    ])
    assert link.trusted is False
    assert "symlink" in link.reason
    owned = mp.judge_posix_chain([
        ("/", 0, 0o755, False),
        ("/etc/agentmetry/policy.yaml", 1000, 0o644, False),
    ])
    assert owned.trusted is False
    assert "1000" in owned.reason


def test_posix_chain_accepts_root_owned_0644():
    verdict = mp.judge_posix_chain([
        ("/", 0, 0o755, False),
        ("/etc", 0, 0o755, False),
        ("/etc/agentmetry", 0, 0o755, False),
        ("/etc/agentmetry/policy.yaml", 0, 0o644, False),
    ])
    assert verdict.trusted is True


def test_windows_acl_rejects_users_modify_and_accepts_system():
    loose = """
C:\\ProgramData\\Agentmetry\\policy.yaml
  NT AUTHORITY\\SYSTEM:(F)
  BUILTIN\\Administrators:(F)
  BUILTIN\\Users:(M)
"""
    assert mp.windows_trust_from_text(loose).trusted is False
    tight = """
C:\\ProgramData\\Agentmetry\\policy.yaml NT AUTHORITY\\SYSTEM:(F)
  BUILTIN\\Administrators:(OI)(CI)(F)
  BUILTIN\\Users:(RX)
  CREATOR OWNER:(OI)(CI)(IO)(F)
"""
    assert mp.windows_trust_from_text(tight).trusted is True


def _quiet_dotenv(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "env_path", lambda: tmp_path / "missing.env")
    monkeypatch.setattr(ps, "_DOTENV_CACHE", (None, {}))


def test_a_lock_beats_the_environment_and_the_user_file(monkeypatch, tmp_path, trusted):
    _quiet_dotenv(monkeypatch, tmp_path)
    managed = tmp_path / "policy.yaml"
    managed.write_text("schema: 1\ndlp_mode: block\n", encoding="utf-8")
    user = Path.home() / ".agentmetry"
    user.mkdir(parents=True, exist_ok=True)
    (user / "policy.yaml").write_text("schema: 1\ndlp_mode: disable\n", encoding="utf-8")
    _candidates(monkeypatch, [managed])
    monkeypatch.setenv("AGENTMETRY_DLP_MODE", "disable")
    assert ps.resolve().dlp_mode == "block"
    layers = mp.load_policy()
    assert layers.locked["dlp_mode"] == "block"
    assert layers.user["dlp_mode"] == "disable"


def test_the_user_file_fills_a_gap_and_the_env_beats_the_user_file(monkeypatch, tmp_path, trusted):
    _quiet_dotenv(monkeypatch, tmp_path)
    _candidates(monkeypatch, [])
    user = Path.home() / ".agentmetry"
    user.mkdir(parents=True, exist_ok=True)
    (user / "policy.yaml").write_text(
        "schema: 1\ntool_policy_mode: block\n", encoding="utf-8"
    )
    monkeypatch.delenv("AGENTMETRY_TOOL_POLICY_MODE", raising=False)
    mp.clear_cache()
    assert ps.resolve().tool_policy_mode == "block"
    monkeypatch.setenv("AGENTMETRY_TOOL_POLICY_MODE", "log")
    mp.clear_cache()
    assert ps.resolve().tool_policy_mode == "log"


def test_a_lock_beats_the_loaded_settings_object(monkeypatch, tmp_path, trusted):
    managed = tmp_path / "policy.yaml"
    managed.write_text("schema: 1\ndlp_mode: block\n", encoding="utf-8")
    _candidates(monkeypatch, [managed])
    monkeypatch.setattr(settings, "dlp_mode", "disable")
    assert ps.policy_settings().dlp_mode == "block"


def test_a_bad_value_refuses_the_whole_managed_file(monkeypatch, tmp_path, trusted):
    managed = tmp_path / "policy.yaml"
    managed.write_text("schema: 1\ndlp_mode: nope\nauth_disabled: false\n", encoding="utf-8")
    _candidates(monkeypatch, [managed])
    layers = mp.load_policy()
    assert layers.locked == {}
    assert layers.rejected
    assert "not" in layers.rejected[0].reason or "dlp_mode" in layers.rejected[0].reason


def test_unknown_schema_is_refused(monkeypatch, tmp_path, trusted):
    managed = tmp_path / "policy.yaml"
    managed.write_text("schema: 99\ndlp_mode: block\n", encoding="utf-8")
    _candidates(monkeypatch, [managed])
    assert mp.load_policy().locked == {}


def test_an_unknown_key_does_not_drop_the_known_ones(monkeypatch, tmp_path, trusted):
    managed = tmp_path / "policy.yaml"
    managed.write_text("schema: 1\ndlp_mode: block\nfuture_knob: 1\n", encoding="utf-8")
    _candidates(monkeypatch, [managed])
    layers = mp.load_policy()
    assert layers.locked["dlp_mode"] == "block"
    assert layers.sources[0].unknown == ("future_knob",)


def test_plist_and_registry_lock(monkeypatch, tmp_path, trusted):
    plist = tmp_path / "ai.agentmetry.sensor.plist"
    with plist.open("wb") as fh:
        plistlib.dump({"schema": 1, "tool_policy_mode": "block"}, fh)
    _candidates(monkeypatch, [plist])
    assert mp.load_policy().locked["tool_policy_mode"] == "block"

    monkeypatch.setattr(mp, "read_registry_policy", lambda: {"dlp_mode": "block", "schema": 1})
    mp.clear_cache()
    layers = mp.load_policy()
    assert layers.locked["dlp_mode"] == "block"
    assert layers.locked["tool_policy_mode"] == "block"


def test_a_managed_preferences_wrapper_unwraps(monkeypatch, tmp_path, trusted):
    plist = tmp_path / "ai.agentmetry.sensor.plist"
    wrapped = {
        "ai.agentmetry.sensor": {
            "Forced": [
                {"mcx_preference_settings": {"schema": 1, "dlp_mode": "block"}},
            ],
        },
    }
    with plist.open("wb") as fh:
        plistlib.dump(wrapped, fh)
    _candidates(monkeypatch, [plist])
    assert mp.load_policy().locked["dlp_mode"] == "block"


def test_payload_metadata_is_not_a_policy_key(monkeypatch, tmp_path, trusted):
    plist = tmp_path / "ai.agentmetry.sensor.plist"
    with plist.open("wb") as fh:
        plistlib.dump(
            {"schema": 1, "dlp_mode": "block", "PayloadUUID": "4F2A9C10-6B3E-4D55-8A71-0C5E91B2D002"},
            fh,
        )
    _candidates(monkeypatch, [plist])
    layers = mp.load_policy()
    assert layers.locked["dlp_mode"] == "block"
    assert layers.sources[0].unknown == ()


def test_the_first_managed_source_wins(monkeypatch, tmp_path, trusted):
    monkeypatch.setattr(mp, "read_registry_policy", lambda: {"dlp_mode": "block", "schema": 1})
    later = tmp_path / "policy.yaml"
    later.write_text("schema: 1\ndlp_mode: disable\n", encoding="utf-8")
    _candidates(monkeypatch, [later])
    # _candidates clears the registry stub. Put it back.
    monkeypatch.setattr(mp, "read_registry_policy", lambda: {"dlp_mode": "block", "schema": 1})
    mp.clear_cache()
    assert mp.load_policy().locked["dlp_mode"] == "block"


def test_overlay_retargets_a_locked_data_dir(monkeypatch, tmp_path, trusted):
    managed = tmp_path / "policy.yaml"
    trail = tmp_path / "var" / "db" / "agentmetry"
    managed.write_text(f"schema: 1\ndata_dir: {trail}\n", encoding="utf-8")
    _candidates(monkeypatch, [managed])
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "old" / "audit-forward.jsonl")
    monkeypatch.setattr(settings, "audit_db_path", settings.audit_db_path)
    monkeypatch.setattr(settings, "detection_live_db_path", settings.detection_live_db_path)
    monkeypatch.setattr(settings, "detection_disposition_db_path", settings.detection_disposition_db_path)
    monkeypatch.setenv("AGENTMETRY_DATA_DIR", "replaced-by-the-lock")
    mp.overlay_settings(settings)
    assert settings.audit_export_path == trail / "audit-forward.jsonl"
    assert settings.audit_db_path == trail / "audit.db"


def test_dir_flags_export_before_a_command_reads_them(tmp_path):
    import os
    from argparse import Namespace

    from agentmetry.cli import _apply_dir_flags

    home = tmp_path / "home"
    data = tmp_path / "data"
    policy = tmp_path / "policy"
    names = ("AGENTMETRY_DATA_DIR", "AGENTMETRY_USER_PROFILE_DIR", "AGENTMETRY_POLICY_DIR")
    before = {name: os.environ.get(name) for name in names}
    try:
        _apply_dir_flags(Namespace(
            data_dir=str(data), user_profile_dir=str(home), policy_dir=str(policy),
        ))
        assert os.environ["AGENTMETRY_DATA_DIR"] == str(data)
        assert os.environ["AGENTMETRY_USER_PROFILE_DIR"] == str(home)
        assert os.environ["AGENTMETRY_POLICY_DIR"] == str(policy)
    finally:
        for name, old in before.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def test_hooks_status_honors_user_profile_dir(tmp_path, capsys):
    import os

    from agentmetry.cli import main

    user = tmp_path / "dev"
    cursor = user / ".cursor"
    cursor.mkdir(parents=True)
    (cursor / "hooks.json").write_text(
        '{"hooks": {"cmd": "python agentmetry_ingest.py cursor hook"}}\n',
        encoding="utf-8",
    )
    old = os.environ.get("AGENTMETRY_USER_PROFILE_DIR")
    try:
        code = main(["hooks", "status", "--user-profile-dir", str(user)])
        captured = capsys.readouterr().out
    finally:
        if old is None:
            os.environ.pop("AGENTMETRY_USER_PROFILE_DIR", None)
        else:
            os.environ["AGENTMETRY_USER_PROFILE_DIR"] = old
    assert code == 0
    assert "cursor" in captured
