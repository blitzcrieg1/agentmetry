"""Driver path tokens and doctor preflight."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.diagnostics.doctor import run_doctor
from core.diagnostics.driver_paths import (
    expand_placeholders,
    load_resolved_driver_specs,
    normalize_drivers_file,
)


def _stub_python(orch: Path) -> str:
    exe = orch / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    return str(exe)


def test_expand_placeholders_resolves_tokens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import core.diagnostics.driver_paths as dp

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(dp, "_ORCH_ROOT", tmp_path / "orch")
    (tmp_path / "orch").mkdir()
    monkeypatch.setattr(dp, "default_python", lambda: _stub_python(tmp_path / "orch"))

    out = expand_placeholders(
        "{PYTHON} {ORCHESTRATOR_ROOT}/tools/x.py {VAULT_PATH}",
        vault_path=vault,
    )
    py_path = _stub_python(tmp_path / "orch")
    assert py_path.replace("\\", "/") in out.replace("\\", "/")
    assert str(vault.resolve()).replace("\\", "/") in out


def test_load_resolved_driver_specs_expands_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import core.config as config_module
    import core.diagnostics.driver_paths as dp

    vault = tmp_path / "vault"
    (vault / ".system").mkdir(parents=True)
    orch = tmp_path / "orch"
    tool = orch / "tools" / "margin_server.py"
    tool.parent.mkdir(parents=True)
    tool.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(dp, "_ORCH_ROOT", orch)
    monkeypatch.setattr(dp, "default_python", lambda: _stub_python(tmp_path / "orch"))
    monkeypatch.setattr(config_module.settings, "vault_path", vault)

    config = vault / ".system" / "drivers.json"
    config.write_text(
        json.dumps({
            "drivers": [{
                "name": "margin",
                "command": "{PYTHON}",
                "args": ["{ORCHESTRATOR_ROOT}/tools/margin_server.py", "{VAULT_PATH}"],
                "enabled": True,
            }]
        }),
        encoding="utf-8",
    )
    specs = load_resolved_driver_specs(config, vault_path=vault)
    assert len(specs) == 1
    assert specs[0].args[0].endswith("margin_server.py")
    assert Path(specs[0].args[1]) == vault.resolve()


def test_normalize_drivers_file_rewrites_absolute_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import core.diagnostics.driver_paths as dp

    vault = tmp_path / "vault"
    (vault / ".system").mkdir(parents=True)
    orch = tmp_path / "orch"
    (orch / "tools").mkdir(parents=True)
    py = _stub_python(orch)
    monkeypatch.setattr(dp, "_ORCH_ROOT", orch)
    monkeypatch.setattr(dp, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(dp, "default_python", lambda: py)

    config = vault / ".system" / "drivers.json"
    config.write_text(
        json.dumps({
            "drivers": [{
                "name": "docs",
                "command": py.replace("\\", "/"),
                "args": [
                    str(orch / "tools" / "docs_server.py").replace("\\", "/"),
                    str(vault.resolve()).replace("\\", "/"),
                ],
                "enabled": True,
            }]
        }),
        encoding="utf-8",
    )

    assert normalize_drivers_file(config, vault_path=vault) is True
    entry = json.loads(config.read_text(encoding="utf-8"))["drivers"][0]
    assert entry["command"] == "{PYTHON}"
    assert entry["args"][0] == "{ORCHESTRATOR_ROOT}/tools/docs_server.py"
    assert entry["args"][1] == "{VAULT_PATH}"


def test_doctor_passes_on_portable_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import core.config as config_module
    import core.diagnostics.driver_paths as dp

    vault = tmp_path / "vault"
    (vault / ".system").mkdir(parents=True)
    orch = tmp_path / "orch"
    (orch / "tools").mkdir(parents=True)
    (orch / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    py = _stub_python(orch)

    monkeypatch.setattr(dp, "_ORCH_ROOT", orch)
    monkeypatch.setattr(dp, "default_python", lambda: py)
    monkeypatch.setattr(config_module.settings, "vault_path", vault)

    config = vault / ".system" / "drivers.json"
    config.write_text(
        json.dumps({
            "drivers": [{
                "name": "docs",
                "command": "{PYTHON}",
                "args": ["{ORCHESTRATOR_ROOT}/tools/docs_server.py", "{VAULT_PATH}"],
                "enabled": False,
            }]
        }),
        encoding="utf-8",
    )

    report = run_doctor(vault_path=vault)
    assert report.exit_code == 0
    assert any(f.code == "drivers_portable" for f in report.findings)
