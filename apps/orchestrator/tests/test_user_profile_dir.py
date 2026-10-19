"""`--user-profile-dir`: a recorder run as root or LocalSystem reads the developer's home.

Under the MSI or a LaunchDaemon, `Path.home()` is the service account's profile.
Hook install, coverage, posture and the MCP inventory all used it, so a service
install wrote hooks where no IDE reads them and attested coverage it did not
have. Naming the developer's home fixes that; leaving it unset changes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pytest

from agentmetry.core import paths
from agentmetry.core.diagnostics import hook_coverage, mcp_inventory, posture

SERVICE_HOME = r"C:\Windows\system32\config\systemprofile"


@pytest.fixture()
def service(monkeypatch, tmp_path):
    """This process runs as LocalSystem; the developer's home is `dev`."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: Path(SERVICE_HOME)))
    for var in ("QWEN_HOME", "KIMI_CODE_HOME", "CODEX_HOME", "COPILOT_HOME"):
        monkeypatch.delenv(var, raising=False)
    dev = tmp_path / "dev"
    dev.mkdir()
    return dev


def _hook_cursor(home: Path) -> None:
    d = home / ".cursor"
    d.mkdir(parents=True, exist_ok=True)
    (d / "hooks.json").write_text(
        json.dumps({"hooks": {"cmd": "python agentmetry_ingest.py cursor hook"}}), encoding="utf-8"
    )


def test_unset_is_the_process_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert paths.user_profile_dir() == tmp_path
    assert paths.named_user_profile() == ""


def test_named_profile_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTMETRY_USER_PROFILE_DIR", str(tmp_path / "dev"))
    assert paths.user_profile_dir() == tmp_path / "dev"


def test_a_service_with_no_named_profile_stays_blind(service):
    assert hook_coverage.profile_blind()
    assert set(hook_coverage.coverage().values()) == {hook_coverage.UNKNOWN}
    assert hook_coverage.attestation_profile() == "service"


def test_a_service_told_whose_home_to_read_sees_that_developer(monkeypatch, service):
    _hook_cursor(service)
    monkeypatch.setenv("AGENTMETRY_USER_PROFILE_DIR", str(service))
    assert not hook_coverage.profile_blind()
    states = hook_coverage.coverage()
    assert states["cursor"] == hook_coverage.COVERED
    assert hook_coverage.attestation_profile() == "user"


def test_hook_install_writes_the_named_profile_not_the_service_home(monkeypatch, service):
    from agentmetry.core.audit import hook_bootstrap

    monkeypatch.setenv("AGENTMETRY_USER_PROFILE_DIR", str(service))
    written = hook_bootstrap.install_claude_global_hooks()
    assert written == service / ".claude" / "settings.json"
    assert "agentmetry_ingest" in written.read_text(encoding="utf-8")


def test_posture_and_mcp_inventory_read_the_named_profile(monkeypatch, service):
    monkeypatch.setenv("AGENTMETRY_USER_PROFILE_DIR", str(service))
    assert posture._codex_home() == service / ".codex"
    user_scoped = [p for _agent, scope, p in mcp_inventory.config_locations() if scope == "user"]
    assert user_scoped
    assert all(p.is_relative_to(service) for p in user_scoped)


@pytest.mark.parametrize("platform, var", [("win32", "APPDATA"), ("linux", "XDG_CONFIG_HOME")])
def test_vscode_ignores_the_service_accounts_own_config_env(monkeypatch, service, platform, var):
    """Under LocalSystem, APPDATA names the SYSTEM profile. A named developer's
    VS Code settings live under their own home, not there."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv(var, r"C:\Windows\system32\config\systemprofile\AppData\Roaming")
    monkeypatch.setenv("AGENTMETRY_USER_PROFILE_DIR", str(service))
    for settings in posture.vscode_user_settings():
        assert settings.is_relative_to(service), settings


@pytest.mark.parametrize("platform, var", [("win32", "APPDATA"), ("linux", "XDG_CONFIG_HOME")])
def test_vscode_still_honours_its_env_for_a_solo_developer(monkeypatch, tmp_path, platform, var):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv(var, str(tmp_path / "custom"))
    assert all(p.is_relative_to(tmp_path / "custom") for p in posture.vscode_user_settings())


@pytest.fixture()
def restored_cli(monkeypatch):
    """`_apply_dir_flags` writes os.environ and two module globals directly;
    pin all four so monkeypatch puts them back."""
    from agentmetry import cli

    monkeypatch.setenv("AGENTMETRY_DATA_DIR", "")
    monkeypatch.setenv("AGENTMETRY_USER_PROFILE_DIR", "")
    monkeypatch.setattr(cli, "_DATA_DIR", cli._DATA_DIR)
    monkeypatch.setattr(cli, "_PID_FILE", cli._PID_FILE)
    return cli


def test_flags_export_before_the_command_runs(restored_cli, tmp_path):
    args = argparse.Namespace(data_dir=str(tmp_path / "data"), user_profile_dir=str(tmp_path / "dev"))
    restored_cli._apply_dir_flags(args)
    assert os.environ["AGENTMETRY_DATA_DIR"] == str(tmp_path / "data")
    assert os.environ["AGENTMETRY_USER_PROFILE_DIR"] == str(tmp_path / "dev")
    assert restored_cli._DATA_DIR == tmp_path / "data"


def test_no_flags_leave_the_data_dir_alone(restored_cli):
    before = restored_cli._DATA_DIR
    restored_cli._apply_dir_flags(argparse.Namespace())
    assert restored_cli._DATA_DIR == before
    assert os.environ["AGENTMETRY_USER_PROFILE_DIR"] == ""


def test_hooks_status_under_a_service_needs_a_named_profile(restored_cli, service, capsys):
    assert restored_cli.main(["hooks", "status"]) == 2
    assert "--user-profile-dir" in capsys.readouterr().err
    _hook_cursor(service)
    assert restored_cli.main(["--user-profile-dir", str(service), "hooks", "status"]) == 0
