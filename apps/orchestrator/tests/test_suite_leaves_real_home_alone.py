"""A test run must never write into the developer's real home directory.

The app's lifespan installs IDE hooks into the home directory on every boot, and
three tests enter that lifespan. Before `_isolate_home` existed, every pytest
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


def test_booting_the_app_writes_hooks_only_into_the_temp_home():
    from fastapi.testclient import TestClient

    from agentmetry.api.main import app

    with TestClient(app):
        pass

    written = Path.home() / ".claude" / "settings.json"
    assert written.is_file(), "the lifespan should still install hooks, just not into the real home"
    # Compare the targets, not ancestry. On Windows pytest's temp directory lives
    # under the user profile, so the isolated home is itself inside the real one
    # and "is it under the real home" is true by construction. What matters is
    # that the file the developer's IDE actually reads was not the one written.
    assert written != REAL_HOME / ".claude" / "settings.json"
