"""Shared test guardrails."""

from __future__ import annotations

import pytest


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
    from core.config import settings

    data = tmp_path_factory.mktemp("agentmetry-data")
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
    from core.audit.detection.disposition import reset_disposition_store
    from core.audit.detection.live_store import reset_live_store_singleton
    from core.audit.ingest import reset_ingest_sink_cache, reset_pending_approvals
    from core.audit.trail_db import reset_trail_db

    reset_trail_db()
    reset_live_store_singleton()
    reset_disposition_store()
    reset_ingest_sink_cache()
    reset_pending_approvals()
