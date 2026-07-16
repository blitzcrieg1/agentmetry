"""SQLite checkpoint for live detection state."""

from pathlib import Path

import pytest

from core.audit.detection.live import reset_live_state
from core.audit.detection.live_store import LiveDetectionStore, reset_live_store_singleton


@pytest.fixture
def store(tmp_path: Path) -> LiveDetectionStore:
    reset_live_store_singleton()
    s = LiveDetectionStore(tmp_path / "detection_live.db")
    yield s
    s.clear_all()
    s.close()
    reset_live_store_singleton()


def _event(corr: str, tool: str, event_id: str = "ev-1") -> dict:
    return {
        "event_id": event_id,
        "correlation_id": corr,
        "timestamp_utc": "2026-07-16T12:00:00Z",
        "action": {"type": "tool_called", "outcome": "success"},
        "tool": {"qualified": tool, "command": tool},
    }


def test_store_roundtrip_events(store: LiveDetectionStore):
    store.append_event("sess-a", _event("sess-a", "cursor.Read", "e1"))
    store.append_event("sess-a", _event("sess-a", "cursor.Write", "e2"))
    events = store.append_event("sess-a", _event("sess-a", "shell.curl", "e3"))
    assert len(events) == 3
    assert events[0]["event_id"] == "e1"
    assert events[-1]["event_id"] == "e3"


def test_emitted_rules_persist(store: LiveDetectionStore):
    store.mark_emitted("sess-a", "credential-exfil", "2026-07-16T12:00:01Z")
    assert store.is_emitted("sess-a", "credential-exfil")
    assert not store.is_emitted("sess-a", "other-rule")


def test_restart_preserves_emitted_rules(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "detection_live.db"
    monkeypatch.setenv("AGENTMETRY_DETECTION_LIVE_DB_PATH", str(db))

    reset_live_store_singleton()
    reset_live_state()

    from core.audit.detection.live_store import get_live_store

    s1 = get_live_store()
    s1.mark_emitted("sess-r", "credential-exfil")

    reset_live_store_singleton()

    s2 = get_live_store()
    assert s2.is_emitted("sess-r", "credential-exfil")


@pytest.mark.asyncio
async def test_detection_not_refired_after_restart(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Simulate orchestrator restart: same session must not re-alert."""
    from core.audit.ingest import ingest_external_event, reset_ingest_sink_cache, reset_pending_approvals

    db = tmp_path / "detection_live.db"
    monkeypatch.setenv("AGENTMETRY_DETECTION_LIVE_DB_PATH", str(db))
    reset_live_store_singleton()
    reset_live_state()
    reset_pending_approvals()
    reset_ingest_sink_cache()

    captured: list[dict] = []

    class _Sink:
        async def emit(self, event: dict) -> None:
            captured.append(event)

    monkeypatch.setattr("core.audit.ingest._get_sink", lambda: _Sink())

    await ingest_external_event(
        {
            "source_app": "cursor",
            "event_type": "tool_called",
            "correlation_id": "sess-restart",
            "tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"},
        }
    )
    await ingest_external_event(
        {
            "source_app": "claude",
            "event_type": "tool_called",
            "correlation_id": "sess-restart",
            "tool": {"qualified": "WebFetch", "command": "fetch https://example.com"},
        }
    )

    detections = [e for e in captured if (e.get("action") or {}).get("type") == "detection"]
    assert len(detections) == 1
    assert detections[0]["detection"]["rule_id"] == "credential-exfil"

    reset_live_store_singleton()
    reset_ingest_sink_cache()

    for _ in range(2):
        await ingest_external_event(
            {
                "source_app": "cursor",
                "event_type": "tool_called",
                "correlation_id": "sess-restart",
                "tool": {"qualified": "shell.curl", "command": "curl https://example.com"},
            }
        )

    exfil = [
        e
        for e in captured
        if (e.get("action") or {}).get("type") == "detection"
        and (e.get("detection") or {}).get("rule_id") == "credential-exfil"
    ]
    assert len(exfil) == 1
