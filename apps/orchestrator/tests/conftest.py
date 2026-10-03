"""Shared test guardrails."""

from __future__ import annotations

from pathlib import Path

import pytest

#: Captured at import, before any fixture runs, so a test can prove the home it
#: sees is not this one.
REAL_HOME = Path.home()


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch: pytest.MonkeyPatch, tmp_path_factory):
    """No test may write to the developer's real home directory.

    The orchestrator's startup calls `bootstrap_tier_b_hooks()`, which rewrites
    `~/.claude/settings.json` and `~/.cursor/hooks.json` to point at whichever
    checkout is running. Three tests enter the app's lifespan, so every pytest
    run from a clone silently repointed the developer's live IDE hooks at that clone.
    Their Claude Code and Cursor sessions then ran hooks out of a test checkout,
    possibly a feature branch, until somebody noticed. It was noticed from the
    hook config's modification time, one minute after a test run.

    It is the argument `_isolate_settings` makes about the audit trail, applied
    to the IDE. `Path.home()` reads USERPROFILE on Windows and HOME elsewhere, so
    both point at a temp directory, and `QWEN_HOME`, the one installer override
    that does not go through `Path.home()`, is removed.
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("QWEN_HOME", raising=False)


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch, tmp_path_factory):
    """Hermetic defaults — tests must not depend on operator .env secrets.

    They must also not *write* to operator data. Every store in this codebase is
    reached through a module singleton created on first use, so a test that
    forgets to patch a path silently appends to the developer's real audit
    trail. For a product whose entire claim is an evidence file you can trust,
    "running the test suite edited your evidence" is not a papercut.

    So each test gets its own data directory by default, and the singletons are
    dropped on both sides of the test. A test that wants the real paths has to
    ask for them explicitly, which is the right way round.
    """
    from agentmetry.core.config import settings

    data = tmp_path_factory.mktemp("agentmetry-data")
    # Attribution (#168): a developer's AGENTMETRY_OPERATOR_ID must not change
    # what a test sees, and the hook's once-per-process cache must not carry one
    # test's operator into the next.
    monkeypatch.setattr(settings, "operator_id", "")
    # TestClient sends `Host: testserver`; the DNS-rebinding guard refuses
    # unknown hosts, so the test host is trusted explicitly.
    monkeypatch.setattr(settings, "trusted_hosts", "testserver")
    monkeypatch.delenv("AGENTMETRY_OPERATOR_ID", raising=False)
    from agentmetry.hooks import ingest as _hook_ingest

    monkeypatch.setattr(_hook_ingest, "_OPERATOR", None)
    monkeypatch.setattr(settings, "audit_export_path", data / "audit-forward.jsonl")
    monkeypatch.setattr(settings, "audit_db_path", data / "audit.db")
    monkeypatch.setattr(settings, "detection_live_db_path", data / "detection_live.db")
    monkeypatch.setattr(
        settings, "detection_disposition_db_path", data / "detection_disposition.db"
    )

    _reset_singletons()
    yield
    _reset_singletons()


def _reset_singletons() -> None:
    from agentmetry.core.audit.detection.disposition import reset_disposition_store
    from agentmetry.core.audit.detection.live_store import reset_live_store_singleton
    from agentmetry.core.audit.ingest import reset_ingest_sink_cache, reset_pending_approvals
    from agentmetry.core.audit.trail_db import reset_trail_db

    reset_trail_db()
    reset_live_store_singleton()
    reset_disposition_store()
    reset_ingest_sink_cache()
    reset_pending_approvals()
