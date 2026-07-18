"""Tests for GET /api/v1/audit/stats and trail_db.stats()."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.config import settings


def _event(
    *,
    corr: str = "sess-1",
    action_type: str = "tool_called",
    outcome: str = "success",
    source: str = "cursor",
    ts: str | None = None,
    extra: dict | None = None,
) -> dict:
    ev = {
        "schema_version": "1.1.0",
        "event_id": f"ev-{corr}-{action_type}",
        "correlation_id": corr,
        "timestamp_utc": ts or datetime.now(timezone.utc).isoformat(),
        "source": {"app": source},
        "action": {"type": action_type, "outcome": outcome},
    }
    if extra:
        ev.update(extra)
    return ev


@pytest.fixture
def stats_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_export_path", tmp_path / "audit-forward.jsonl")
    monkeypatch.setattr(settings, "audit_export_enabled", True)
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from core.audit.trail_db import get_trail_db, reset_trail_db

    reset_trail_db()
    db = get_trail_db()
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=10)).isoformat()
    events = [
        _event(corr="s1", source="cursor"),
        _event(corr="s1", action_type="detection", outcome="success"),
        _event(
            corr="s2",
            outcome="denied",
            extra={"dlp": {"rule_id": "aws_access_key", "mode": "block"}},
        ),
        _event(
            corr="s3",
            outcome="denied",
            extra={
                "tool_policy": {
                    "rule_id": "block_shell_rm",
                    "action": "deny",
                    "mode": "block",
                    "blocked": True,
                }
            },
        ),
        _event(corr="old", ts=old_ts),
    ]
    db.insert_batch(events)

    from api.main import app

    return TestClient(app)


def test_audit_stats_endpoint(stats_client: TestClient):
    body = stats_client.get("/api/v1/audit/stats?days=7").json()
    assert body["enabled"] is True
    assert body["total_events"] == 4
    assert body["sessions"] == 3
    assert body["detections"] == 1
    assert body["denied"] == 2
    assert body["dlp_matches"] == 1
    assert body["tool_policy_blocks"] == 1
    assert body["by_source"]["cursor"] == 4


def test_trail_db_stats_excludes_outside_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "audit_db_path", tmp_path / "audit.db")
    from core.audit.trail_db import AuditTrailDB, reset_trail_db

    reset_trail_db()
    db = AuditTrailDB(tmp_path / "audit.db")
    recent = _event(corr="recent")
    stale = _event(corr="stale", ts=(datetime.now(timezone.utc) - timedelta(days=30)).isoformat())
    db.insert_batch([recent, stale])

    stats = db.stats(window_days=7)
    assert stats["total_events"] == 1
    assert stats["sessions"] == 1
