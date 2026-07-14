"""End-to-end: a DLP verdict survives ingest, and detections stream to the sinks.

These cover two bugs that made shipped features silently inert:
  - a `log`-mode DLP match was computed in the hook and then dropped at the API
    boundary, so it appeared nowhere in the trail;
  - detections only existed if a human opened the session, so nothing ever
    reached a SIEM or an alert webhook.
"""

from __future__ import annotations

import pytest

from core.audit.detection.live import reset_live_state
from core.audit.external import build_external_canonical
from core.audit.ingest import ingest_external_event, reset_ingest_sink_cache, reset_pending_approvals


class _CapturingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def sink(monkeypatch: pytest.MonkeyPatch) -> _CapturingSink:
    reset_live_state()
    reset_pending_approvals()
    reset_ingest_sink_cache()
    s = _CapturingSink()
    monkeypatch.setattr("core.audit.ingest._get_sink", lambda: s)
    return s


def _tool_payload(corr: str, tool: str, *, dlp: dict | None = None) -> dict:
    payload = {
        "source_app": "cursor",
        "event_type": "tool_called",
        "correlation_id": corr,
        "tool": {"qualified": tool, "command": f"{tool} run"},
    }
    if dlp:
        payload["dlp"] = dlp
    return payload


# --- DLP persistence ---------------------------------------------------------

def test_dlp_verdict_survives_canonicalization():
    """A log-mode match must be recorded on the event, not silently dropped."""
    event = build_external_canonical(
        _tool_payload(
            "sess-dlp",
            "cursor.Shell",
            dlp={
                "rule_id": "aws_access_key",
                "mode": "log",
                "pattern_type": "regex",
                "category": "credentials",
                "severity": "critical",
                "rule_ids": ["aws_access_key"],
            },
        )
    )
    assert event["dlp"]["rule_id"] == "aws_access_key"
    assert event["dlp"]["mode"] == "log"
    assert event["dlp"]["severity"] == "critical"
    assert event["dlp"]["category"] == "credentials"


def test_dlp_absent_when_no_match():
    event = build_external_canonical(_tool_payload("sess-clean", "cursor.Read"))
    assert "dlp" not in event


def test_dlp_never_carries_the_matched_value():
    """Rule metadata only — the secret itself must never reach the trail."""
    event = build_external_canonical(
        _tool_payload(
            "sess-dlp2",
            "cursor.Shell",
            dlp={"rule_id": "github_pat", "mode": "log", "value": "ghp_SHOULD_NOT_PERSIST"},
        )
    )
    assert "value" not in event["dlp"]
    assert "SHOULD_NOT_PERSIST" not in str(event)


@pytest.mark.asyncio
async def test_dlp_verdict_reaches_the_sink(sink: _CapturingSink):
    await ingest_external_event(
        _tool_payload(
            "sess-e2e",
            "cursor.Shell",
            dlp={"rule_id": "slack_token", "mode": "log", "severity": "critical"},
        )
    )
    assert sink.events[0]["dlp"]["rule_id"] == "slack_token"


# --- streamed detections -----------------------------------------------------

@pytest.mark.asyncio
async def test_credential_exfil_streams_as_a_detection_event(sink: _CapturingSink):
    """Read a key, then egress: a detection event must hit the sink unprompted."""
    await ingest_external_event(
        _tool_payload("sess-x", "cursor.Read") | {"tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"}}
    )
    await ingest_external_event(
        {"source_app": "claude", "event_type": "tool_called", "correlation_id": "sess-x",
         "tool": {"qualified": "WebFetch", "command": "fetch https://example.com"}}
    )

    detections = [e for e in sink.events if (e.get("action") or {}).get("type") == "detection"]
    assert len(detections) == 1
    d = detections[0]
    assert d["detection"]["rule_id"] == "credential-exfil"
    assert d["action"]["outcome"] == "critical"  # severity, so a SIEM can alert on it
    assert d["correlation_id"] == "sess-x"
    assert d["source_topic"] == "detection/credential-exfil"


@pytest.mark.asyncio
async def test_detection_emitted_once_per_session(sink: _CapturingSink):
    """A firing rule must not re-alert on every subsequent event."""
    await ingest_external_event(
        {"source_app": "cursor", "event_type": "tool_called", "correlation_id": "sess-y",
         "tool": {"qualified": "cursor.Read", "command": "cat ~/.aws/credentials"}}
    )
    for _ in range(3):
        await ingest_external_event(
            {"source_app": "cursor", "event_type": "tool_called", "correlation_id": "sess-y",
             "tool": {"qualified": "shell.curl", "command": "curl https://example.com"}}
        )

    detections = [e for e in sink.events if (e.get("action") or {}).get("type") == "detection"]
    assert len(detections) == 1


@pytest.mark.asyncio
async def test_benign_session_emits_no_detection(sink: _CapturingSink):
    await ingest_external_event(_tool_payload("sess-ok", "cursor.Read"))
    await ingest_external_event(_tool_payload("sess-ok", "cursor.Write"))
    assert not [e for e in sink.events if (e.get("action") or {}).get("type") == "detection"]


@pytest.mark.asyncio
async def test_sessions_are_isolated(sink: _CapturingSink):
    """A credential read in one session must not pair with egress in another."""
    await ingest_external_event(
        {"source_app": "cursor", "event_type": "tool_called", "correlation_id": "sess-a",
         "tool": {"qualified": "cursor.Read", "command": "cat ~/.ssh/id_rsa"}}
    )
    await ingest_external_event(
        {"source_app": "cursor", "event_type": "tool_called", "correlation_id": "sess-b",
         "tool": {"qualified": "shell.curl", "command": "curl https://example.com"}}
    )
    assert not [e for e in sink.events if (e.get("action") or {}).get("type") == "detection"]
