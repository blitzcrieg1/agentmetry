"""A detection is checkpointed only after it is durably stored and forwarded.

High #2 from the 2026-07-18 review: the old flow marked a rule emitted inside
observe(), before the sink emit. If emit threw, the rule was never re-fired for
that session and the alert was silently lost. Now the checkpoint happens after a
successful emit, so a transient sink failure lets the detection fire again on the
next session event — without double-alerting once it finally succeeds.
"""

from __future__ import annotations

import pytest

from core.audit.detection.live import reset_live_state
from core.audit.detection.live_store import get_live_store
from core.audit.ingest import (
    ingest_external_event,
    reset_ingest_sink_cache,
    reset_pending_approvals,
)


class _FlakyDetectionSink:
    """Fails the first detection emit, then succeeds. Regular events always pass."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self._detection_failures = 0
        self._fail_detections = 1

    async def emit(self, event: dict) -> None:
        is_detection = (event.get("action") or {}).get("type") == "detection"
        if is_detection and self._detection_failures < self._fail_detections:
            self._detection_failures += 1
            raise RuntimeError("sink down")
        self.events.append(event)

    def detections(self) -> list[dict]:
        return [e for e in self.events if (e.get("action") or {}).get("type") == "detection"]


@pytest.fixture
def flaky_sink(monkeypatch: pytest.MonkeyPatch) -> _FlakyDetectionSink:
    reset_live_state()
    reset_pending_approvals()
    reset_ingest_sink_cache()
    s = _FlakyDetectionSink()
    monkeypatch.setattr("core.audit.ingest._get_sink", lambda: s)
    return s


def _cred_read(corr: str) -> dict:
    return {
        "source_app": "cursor",
        "event_type": "tool_called",
        "correlation_id": corr,
        "tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"},
    }


def _egress(corr: str) -> dict:
    return {
        "source_app": "claude",
        "event_type": "tool_called",
        "correlation_id": corr,
        "tool": {"qualified": "WebFetch", "command": "fetch https://example.com"},
    }


@pytest.mark.asyncio
async def test_failed_emit_refires_and_marks_only_after_success(flaky_sink: _FlakyDetectionSink):
    corr = "sess-flaky"
    await ingest_external_event(_cred_read(corr))

    # Egress triggers credential-exfil, but the sink fails this first emit.
    await ingest_external_event(_egress(corr))
    assert flaky_sink.detections() == []  # never forwarded
    assert not get_live_store().is_emitted(corr, "credential-exfil")  # not checkpointed

    # Next session event: the rule is still eligible, and now succeeds.
    await ingest_external_event(_egress(corr))
    dets = flaky_sink.detections()
    assert len(dets) == 1
    assert dets[0]["detection"]["rule_id"] == "credential-exfil"
    assert get_live_store().is_emitted(corr, "credential-exfil")  # checkpointed after success


@pytest.mark.asyncio
async def test_no_duplicate_detection_after_success(flaky_sink: _FlakyDetectionSink):
    corr = "sess-once"
    await ingest_external_event(_cred_read(corr))
    await ingest_external_event(_egress(corr))  # fails once, not marked
    await ingest_external_event(_egress(corr))  # re-fires, succeeds -> 1 detection
    await ingest_external_event(_egress(corr))  # already emitted -> no dup
    await ingest_external_event(_egress(corr))  # still no dup

    assert len(flaky_sink.detections()) == 1
