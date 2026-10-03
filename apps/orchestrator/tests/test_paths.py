"""Where data and .env live (pilot hardening item 10).

An installed wheel computed every default relative to the package: the trail
went to `site-packages/data/audit-forward.jsonl` and `.env` was read from
`site-packages/.env`. A checkout must not move; an install must use the
platform's per-user data directory; the hook and the orchestrator must agree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentmetry.core import paths


@pytest.fixture()
def installed(monkeypatch, tmp_path):
    """Pretend the package lives in a site-packages with no pyproject beside it."""
    site = tmp_path / "site-packages"
    (site / "agentmetry").mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKAGE_PARENT", site)
    for name in ("AGENTMETRY_DATA_DIR", "AGENTMETRY_INSTALL_ROOT"):
        monkeypatch.delenv(name, raising=False)
    return site


def test_the_checkout_keeps_its_data_where_it_was(monkeypatch):
    monkeypatch.delenv("AGENTMETRY_DATA_DIR", raising=False)
    monkeypatch.delenv("AGENTMETRY_INSTALL_ROOT", raising=False)
    assert paths.is_checkout()
    assert paths.data_dir() == paths.PACKAGE_PARENT / "data"
    assert paths.env_file() == paths.PACKAGE_PARENT / ".env"


def test_an_install_never_uses_site_packages(installed):
    assert not paths.is_checkout()
    assert installed not in paths.data_dir().parents and paths.data_dir() != installed / "data"
    assert paths.env_file() == paths.data_dir() / ".env"


def test_an_install_uses_the_platform_user_data_dir(installed, monkeypatch, tmp_path):
    import os
    import sys

    if os.name == "nt":
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
        assert paths.data_dir() == tmp_path / "Local" / "Agentmetry"
    elif sys.platform == "darwin":
        assert paths.data_dir() == Path.home() / "Library" / "Application Support" / "Agentmetry"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert paths.data_dir() == tmp_path / "xdg" / "agentmetry"


def test_an_explicit_data_dir_wins(installed, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTMETRY_DATA_DIR", str(tmp_path / "explicit"))
    monkeypatch.setenv("AGENTMETRY_INSTALL_ROOT", str(tmp_path / "msi"))
    assert paths.data_dir() == tmp_path / "explicit"
    assert paths.env_file() == tmp_path / "explicit" / ".env"


def test_the_msi_install_root_is_honoured(installed, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTMETRY_INSTALL_ROOT", str(tmp_path / "msi"))
    assert paths.data_dir() == tmp_path / "msi" / "data"


def test_legacy_site_packages_data_is_reported_not_moved(installed):
    assert paths.legacy_site_packages_data() is None
    (installed / "data").mkdir()
    (installed / "data" / "audit-forward.jsonl").write_text("{}\n", encoding="utf-8")
    assert paths.legacy_site_packages_data() == installed / "data"
    assert (installed / "data" / "audit-forward.jsonl").exists()


def test_the_hook_and_the_orchestrator_agree(monkeypatch):
    """The hook spools where the orchestrator drains. A mismatch is a spool
    nobody ever replays."""
    from agentmetry.hooks import ingest

    monkeypatch.delenv("AGENTMETRY_AUDIT_EXPORT_PATH", raising=False)
    monkeypatch.delenv("AGENTMETRY_DATA_DIR", raising=False)
    monkeypatch.delenv("AGENTMETRY_INSTALL_ROOT", raising=False)
    assert ingest._data_dir() == paths.data_dir()


def test_the_resolver_costs_the_hook_no_third_party_import():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c",
         "import sys, agentmetry.core.paths; "
         "print(sorted(m for m in sys.modules if m.split('.')[0] in ('platformdirs', 'pydantic')))"],
        capture_output=True, text=True, timeout=60, check=True,
    )
    assert out.stdout.strip() == "[]"
