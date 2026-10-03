"""A test run must never write into the developer's real home directory.

The app's lifespan used to install IDE hooks into the home directory on every
boot (now only with AGENTMETRY_AUTO_INSTALL_HOOKS=1), and three tests enter that lifespan. Before `_isolate_home` existed, every pytest
run repointed the developer's live Claude Code and Cursor hooks at whichever
checkout ran the tests. The configs were found aimed at a feature branch one
minute after a run.

These tests boot the real app rather than calling the installer, because the
installer was never the problem: `test_hook_bootstrap.py` already patches
`Path.home` for itself. The leak was the startup path nobody thought of as a
write.
"""

from __future__ import annotations

from pathlib import Path

from conftest import REAL_HOME


def test_the_home_a_test_sees_is_not_the_real_one():
    assert Path.home() != REAL_HOME


def test_a_default_boot_writes_no_hook_config_at_all():
    """Pilot hardening item 14. Booting used to rewrite the global IDE hook
    configs every time, which is how a second checkout took over live hooks."""
    from fastapi.testclient import TestClient

    from agentmetry.api.main import app
    from agentmetry.core.config import settings

    assert settings.auto_install_hooks is False
    with TestClient(app):
        pass

    assert not (Path.home() / ".claude" / "settings.json").exists()
    assert not (Path.home() / ".cursor" / "hooks.json").exists()


def test_an_opted_in_boot_writes_hooks_only_into_the_temp_home(monkeypatch):
    from fastapi.testclient import TestClient

    from agentmetry.api.main import app
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "auto_install_hooks", True)
    with TestClient(app):
        pass

    written = Path.home() / ".claude" / "settings.json"
    assert written.is_file(), "with the opt-in, the lifespan installs hooks, just not into the real home"
    # Compare the targets, not ancestry. On Windows pytest's temp directory lives
    # under the user profile, so the isolated home is itself inside the real one
    # and "is it under the real home" is true by construction. What matters is
    # that the file the developer's IDE actually reads was not the one written.
    assert written != REAL_HOME / ".claude" / "settings.json"
