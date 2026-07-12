"""Tests for AgentAudit file, webhook, Elastic, and Splunk sinks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.audit.adapters.ecs import canonical_to_ecs
from core.audit.adapters.splunk import canonical_to_hec_event
from core.audit.sinks import (
    ElasticEcsSink,
    FileAuditSink,
    MultiAuditSink,
    SplunkHecSink,
    WebhookAuditSink,
    build_audit_sinks,
    parse_sink_modes,
)


@pytest.mark.asyncio
async def test_file_sink_appends_jsonl(tmp_path: Path):
    path = tmp_path / "out.jsonl"
    sink = FileAuditSink(path)
    event = {"schema_version": "1.0.0", "event_id": "abc"}
    await sink.emit(event)
    await sink.emit(event)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == "abc"


@pytest.mark.asyncio
async def test_webhook_sink_posts_json():
    sink = WebhookAuditSink("http://collector.test/ingest", timeout_seconds=2.0)
    payload = {"action": {"type": "tool_called", "outcome": "success"}}

    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("core.audit.sinks.httpx.AsyncClient", return_value=mock_client):
        await sink.emit(payload)

    mock_client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_elastic_sink_posts_ecs_document():
    canonical = {
        "event_id": "e1",
        "timestamp_utc": "2026-07-12T10:00:00+00:00",
        "host_id": "host1",
        "correlation_id": "t1",
        "session_id": "s1",
        "seq": 1,
        "schema_version": "1.0.0",
        "actor": {"id": "u1", "role": "operator", "type": "user"},
        "action": {"type": "tool_called", "outcome": "denied", "reason": "not_allowed"},
        "agent": {"name": "blackbox", "skill_id": "x"},
        "tool": {"name": "run", "qualified": "shell.run", "server": "shell"},
        "model": {"id": "gemini", "provider": "gemini"},
    }
    sink = ElasticEcsSink("https://elastic.test:9200", "logs-agentaudit", "id:secret")

    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("core.audit.sinks.httpx.AsyncClient", return_value=mock_client):
        await sink.emit(canonical)

    call_kwargs = mock_client.post.await_args.kwargs
    body = call_kwargs["json"]
    assert body["event"]["action"] == "tool_called"
    assert body["event"]["outcome"] == "denied"
    assert body["agentaudit"]["event_id"] == "e1"
    assert call_kwargs["headers"]["Authorization"] == "ApiKey id:secret"


@pytest.mark.asyncio
async def test_splunk_sink_posts_hec_envelope():
    canonical = {
        "event_id": "e2",
        "timestamp_utc": "2026-07-12T10:00:00+00:00",
        "host_id": "host1",
        "correlation_id": "t2",
        "actor": {"id": "u2"},
        "action": {"type": "config_change", "outcome": "success"},
    }
    sink = SplunkHecSink("https://splunk.test:8088", "hec-token", index="agentaudit")

    mock_response = AsyncMock()
    mock_response.raise_for_status = lambda: None
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("core.audit.sinks.httpx.AsyncClient", return_value=mock_client):
        await sink.emit(canonical)

    payload = mock_client.post.await_args.kwargs["json"]
    assert payload["index"] == "agentaudit"
    assert payload["event"]["event_id"] == "e2"
    assert payload["fields"]["action_type"] == "config_change"
    assert mock_client.post.await_args.kwargs["headers"]["Authorization"] == "Splunk hec-token"


def test_canonical_to_ecs_maps_core_fields():
    doc = canonical_to_ecs({
        "event_id": "x",
        "timestamp_utc": "2026-07-12T10:00:00+00:00",
        "host_id": "h",
        "correlation_id": "c",
        "session_id": "s",
        "seq": 3,
        "actor": {"id": "u", "role": "operator"},
        "action": {"type": "tool_called", "outcome": "success", "reason": ""},
        "agent": {"name": "blackbox"},
        "schema_version": "1.0.0",
    })
    assert doc["event"]["action"] == "tool_called"
    assert doc["trace"]["id"] == "c"
    assert doc["user"]["id"] == "u"


def test_canonical_to_hec_event():
    hec = canonical_to_hec_event(
        {
            "timestamp_utc": "2026-07-12T10:00:00+00:00",
            "host_id": "lab",
            "correlation_id": "t1",
            "actor": {"id": "solo"},
            "action": {"type": "tool_called", "outcome": "denied"},
        },
        index="main",
        sourcetype="agentaudit:json",
    )
    assert hec["host"] == "lab"
    assert hec["fields"]["actor_id"] == "solo"
    assert hec["time"] > 0


def test_parse_sink_modes():
    assert parse_sink_modes("file") == {"file"}
    assert parse_sink_modes("both") == {"file", "webhook"}
    assert parse_sink_modes("file,elastic,splunk") == {"file", "elastic", "splunk"}
    assert parse_sink_modes("all") == {"file", "webhook", "elastic", "splunk"}


def test_build_audit_sinks_elastic_and_splunk(tmp_path: Path):
    sink = build_audit_sinks(
        modes={"file", "elastic", "splunk"},
        file_path=tmp_path / "a.jsonl",
        webhook_url="",
        webhook_timeout_seconds=3.0,
        elastic_url="https://elastic.test",
        elastic_index="logs-agentaudit",
        elastic_api_key="k:secret",
        elastic_verify_tls=True,
        splunk_hec_url="https://splunk.test:8088",
        splunk_hec_token="token",
        splunk_index="main",
        splunk_sourcetype="agentaudit:json",
        splunk_verify_tls=True,
    )
    assert isinstance(sink, MultiAuditSink)
    assert len(sink._sinks) == 3


def test_build_audit_sinks_none_when_empty(tmp_path: Path):
    assert build_audit_sinks(
        modes=set(),
        file_path=tmp_path / "a.jsonl",
        webhook_url="",
        webhook_timeout_seconds=3.0,
        elastic_url="",
        elastic_index="logs-agentaudit",
        elastic_api_key="",
        elastic_verify_tls=True,
        splunk_hec_url="",
        splunk_hec_token="",
        splunk_index="main",
        splunk_sourcetype="agentaudit:json",
        splunk_verify_tls=True,
    ) is None
