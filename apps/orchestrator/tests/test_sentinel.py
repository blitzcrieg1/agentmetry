"""Microsoft Sentinel output (pilot hardening item 25).

Checked against the Logs Ingestion API reference, not against Azure: the URI
shape, the client-credentials token for https://monitor.azure.com, a JSON array
body, and the record columns the DCR declares. The docs are tested too, because
a column the DCR does not declare is dropped silently and a rule missing from
the KQL page is a detection a Sentinel customer never sees.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import pytest

from agentmetry.core.audit.adapters.sentinel import COLUMNS, canonical_to_sentinel_record
from agentmetry.core.audit.forwarder import ForwardError
from agentmetry.core.audit.sinks import SentinelLogsIngestionSink, build_audit_sinks, parse_sink_modes

_REPO = Path(__file__).resolve().parents[3]
_DOCS = _REPO / "docs" / "integrations"
_RESERVED = {"_ResourceId", "id", "_SubscriptionId", "TenantId", "Type", "UniqueId", "Title"}


def _detection() -> dict:
    return {
        "event_id": "e1", "schema_version": "1.2.0", "timestamp_utc": "2026-10-03T10:00:00+00:00",
        "correlation_id": "c1", "session_id": "s1", "host_id": "dev-17", "fleet_id": "eu-pilot",
        "source": {"tier": "detection", "app": "agentmetry"}, "actor": {"id": "CORP\\ana"},
        "action": {"type": "detection", "outcome": "critical", "reason": "read ~/.ssh then curl"},
        "detection": {"rule_id": "credential-exfil", "severity": "critical", "title": "Credential access",
                      "tactic_ids": ["TA0006", "TA0011"], "technique_ids": ["T1552.004", "T1071.001"]},
    }


def test_a_record_has_exactly_the_declared_columns():
    record = canonical_to_sentinel_record(_detection())
    assert list(record) == list(COLUMNS)
    assert record["RuleId"] == "credential-exfil" and record["FleetId"] == "eu-pilot"
    assert record["TechniqueIds"] == ["T1552.004", "T1071.001"]
    assert record["Event"]["detection"]["title"] == "Credential access", "the whole event travels"


def test_column_names_are_legal_in_log_analytics():
    for name in COLUMNS:
        assert name not in _RESERVED, f"{name} is reserved"
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,44}", name), name


def test_a_tool_event_carries_its_mitre_mapping():
    record = canonical_to_sentinel_record({
        "action": {"type": "tool_called"}, "tool": {"qualified": "Bash", "input_redaction": "hmac+command",
                                                    "mitre": {"tactic_id": "TA0002", "technique_id": "T1059"}},
    })
    assert record["TacticIds"] == ["TA0002"] and record["TechniqueIds"] == ["T1059"]
    assert record["InputRedaction"] == "hmac+command"


def _sink() -> SentinelLogsIngestionSink:
    return SentinelLogsIngestionSink(
        "https://agm-dcr.westeurope-1.ingest.monitor.azure.com", "dcr-0123",
        tenant_id="tenant-1", client_id="client-1", client_secret="secret-1",  # gitleaks:allow
    )


def _transport(seen: list[httpx.Request], *, ingest_status: int = 204):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(ingest_status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_batch_is_one_authenticated_post_to_the_dcr_stream():
    seen: list[httpx.Request] = []
    sink = _sink()
    async with _transport(seen) as client:
        await sink.send_batch(client, [_detection(), _detection()])
        await sink.send_batch(client, [_detection()])
    token, ingest, second = seen
    assert str(token.url) == "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token"
    assert b"scope=https%3A%2F%2Fmonitor.azure.com%2F.default" in token.content
    assert b"grant_type=client_credentials" in token.content
    assert ingest.url.path == "/dataCollectionRules/dcr-0123/streams/Custom-Agentmetry_CL"
    assert ingest.url.params["api-version"] == "2023-01-01"
    assert ingest.headers["authorization"] == "Bearer tok"
    body = json.loads(ingest.content)
    assert isinstance(body, list) and len(body) == 2
    assert second.url.host != "login.microsoftonline.com", "the token is cached, not fetched per batch"


@pytest.mark.parametrize(("status", "retryable"), [(500, True), (503, True), (429, True), (400, False), (413, False)])
async def test_failures_are_classified(status: int, retryable: bool):
    async with _transport([], ingest_status=status) as client:
        with pytest.raises(ForwardError) as exc:
            await _sink().send_batch(client, [_detection()])
    assert exc.value.retryable is retryable


async def test_a_rejected_token_is_dropped_and_retried():
    seen: list[httpx.Request] = []
    sink = _sink()
    async with _transport(seen, ingest_status=403) as client:
        with pytest.raises(ForwardError) as exc:
            await sink.send_batch(client, [_detection()])
    assert exc.value.retryable
    assert sink._token == "", "a 401/403 must fetch a fresh token next time"


def test_the_sink_is_built_only_when_fully_configured(tmp_path: Path):
    common = dict(
        modes={"sentinel"}, file_path=tmp_path / "t.jsonl", webhook_url="", webhook_timeout_seconds=5,
        elastic_url="", elastic_index="", elastic_api_key="", elastic_verify_tls=True,
        splunk_hec_url="", splunk_hec_token="", splunk_index="", splunk_sourcetype="", splunk_verify_tls=True,
    )
    full = dict(sentinel_endpoint="https://x.ingest.monitor.azure.com", sentinel_dcr_id="dcr-1",
                sentinel_tenant_id="t", sentinel_client_id="c", sentinel_client_secret="s")
    assert isinstance(build_audit_sinks(**common, **full), SentinelLogsIngestionSink)
    assert build_audit_sinks(**common, **{**full, "sentinel_client_secret": ""}) is None
    assert "sentinel" in parse_sink_modes("all")


def test_the_secret_never_appears_in_the_settings_repr(monkeypatch):
    from agentmetry.core.config import settings

    monkeypatch.setattr(settings, "audit_sentinel_client_secret", "do-not-log-me")
    assert "do-not-log-me" not in repr(settings)


# --- the docs ----------------------------------------------------------------


def test_the_documented_dcr_declares_exactly_the_record_columns():
    text = (_DOCS / "sentinel.md").read_text(encoding="utf-8")
    block = next(b for b in re.findall(r"```json\n(.*?)```", text, flags=re.S) if "streamDeclarations" in b)
    dcr = json.loads(block.replace("<workspace region>", "x").replace("<workspace resource id>", "x"))
    columns = dcr["properties"]["streamDeclarations"]["Custom-Agentmetry_CL"]["columns"]
    assert {c["name"]: c["type"] for c in columns} == COLUMNS


def test_every_shipped_rule_is_on_the_sentinel_page():
    rules = set(re.findall(
        r'rule_id="([a-z0-9-]+)"',
        (_REPO / "apps/orchestrator/agentmetry/core/audit/detection/rules.py").read_text(encoding="utf-8"),
    ))
    page = (_DOCS / "detections-sentinel.md").read_text(encoding="utf-8")
    missing = sorted(r for r in rules if f"`{r}`" not in page)
    assert rules and not missing, f"rules missing from detections-sentinel.md: {missing}"


def test_no_em_dashes_in_the_new_docs():
    for name in ("sentinel.md", "detections-sentinel.md"):
        assert "—" not in (_DOCS / name).read_text(encoding="utf-8"), name
