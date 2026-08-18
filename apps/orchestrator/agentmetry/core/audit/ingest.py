"""Ingest external adapter events into Agentmetry sinks (Tier B)."""

from __future__ import annotations

import logging
from typing import Any

from agentmetry.core.audit.detection.live import (
    build_detection_event,
    mark_detection_emitted,
    mark_host_detection_emitted,
    observe,
    observe_host,
)
from agentmetry.core.audit.external import build_external_canonical
from agentmetry.core.audit.sinks import build_audit_sinks, parse_sink_modes
from agentmetry.core.config import settings

logger = logging.getLogger(__name__)

_sink = None

# Best-effort, in-session approval correlation (Tier B). No IDE reports "the
# human clicked approve", so we infer it: a tool that RUNS after an `ask` means
# the human approved; an `ask` still pending at session end means denied/aborted.
# Inferred events are explicitly marked `reason: inferred:*` — never presented
# as a native approval signal. In-memory only (lost on restart); approvals are
# short-lived within a session so this is acceptable for a local recorder.
_pending_approvals: dict[str, list[dict[str, str]]] = {}
_MAX_PENDING_PER_CORR = 64


def reset_ingest_sink_cache() -> None:
    """Test helper — clear lazy sink singleton."""
    global _sink
    _sink = None


def reset_pending_approvals() -> None:
    """Test helper — clear the approval-correlation state."""
    _pending_approvals.clear()


def _tool_ident(canonical: dict[str, Any]) -> tuple[str, str, str]:
    tool = canonical.get("tool") or {}
    return (
        str(tool.get("qualified") or ""),
        str(tool.get("server") or ""),
        str(tool.get("input_hash") or ""),
    )


def _approval_matches(pending: dict[str, str], qualified: str, input_hash: str) -> bool:
    """Does this executed call satisfy that pending approval?

    Bind on the most specific identity both sides carry, the same precedence
    rule_approval_denied_then_executed uses. When both know the argument hash
    they must agree: an approval for `Bash(rm -rf /tmp/x)` must not be consumed
    by a later `Bash(ls)`, or the trail claims a human approved something they
    never saw. That gap between the proposed action and the one that ran is
    exactly where surprises live.

    Falls back to the tool name only when a hash is missing on either side,
    which is the pre-hash adapter case. An approval recorded with no tool name
    still matches anything, as before.
    """
    if pending.get("tool") and pending["tool"] != qualified:
        return False
    if pending.get("input_hash") and input_hash:
        return pending["input_hash"] == input_hash
    return True


def _approval_payload(
    source_app: str, corr: str, pending: dict[str, str], outcome: str, reason: str
) -> dict[str, Any]:
    return {
        "source_app": source_app,
        "adapter": f"{source_app}_inferred",
        "event_type": "approval_response",
        "outcome": outcome,
        "reason": reason,
        "correlation_id": corr,
        "gated_action": {
            "tool": pending.get("tool", ""),
            "server": pending.get("server", ""),
            "input_hash": pending.get("input_hash", ""),
        },
    }


def infer_approval_payloads(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    """Return synthetic approval_response payloads inferred from the event stream."""
    action = canonical.get("action") or {}
    atype = action.get("type")
    outcome = action.get("outcome")
    corr = str(canonical.get("correlation_id") or "")
    if not corr:
        return []
    source_app = str((canonical.get("source") or {}).get("app") or "cursor")

    if atype == "approval_request" and outcome == "pending":
        qualified, server, input_hash = _tool_ident(canonical)
        bucket = _pending_approvals.setdefault(corr, [])
        if len(bucket) < _MAX_PENDING_PER_CORR:
            bucket.append({"tool": qualified, "server": server, "input_hash": input_hash})
        return []

    if atype == "tool_called" and outcome == "success":
        bucket = _pending_approvals.get(corr) or []
        qualified, _server, input_hash = _tool_ident(canonical)
        for i, pending in enumerate(bucket):
            if _approval_matches(pending, qualified, input_hash):
                bucket.pop(i)
                return [
                    _approval_payload(
                        source_app, corr, pending, "success", "inferred:tool_ran_after_ask"
                    )
                ]
        return []

    if atype == "session_end":
        bucket = _pending_approvals.pop(corr, [])
        return [
            _approval_payload(
                source_app, corr, pending, "denied", "inferred:session_ended_pending"
            )
            for pending in bucket
        ]

    return []


def _get_sink():
    global _sink
    if _sink is not None:
        return _sink
    if not settings.audit_export_enabled:
        return None
    modes = parse_sink_modes(settings.audit_sink)
    _sink = build_audit_sinks(
        modes=modes,
        file_path=settings.audit_export_path,
        webhook_url=settings.audit_webhook_url,
        webhook_timeout_seconds=settings.audit_webhook_timeout_seconds,
        webhook_format=settings.audit_webhook_format,
        elastic_url=settings.audit_elastic_url,
        elastic_index=settings.audit_elastic_index,
        elastic_api_key=settings.audit_elastic_api_key,
        elastic_verify_tls=settings.audit_elastic_verify_tls,
        splunk_hec_url=settings.audit_splunk_hec_url,
        splunk_hec_token=settings.audit_splunk_hec_token,
        splunk_index=settings.audit_splunk_index,
        splunk_sourcetype=settings.audit_splunk_sourcetype,
        splunk_verify_tls=settings.audit_splunk_verify_tls,
        chronicle_endpoint=settings.audit_chronicle_endpoint,
        chronicle_customer_id=settings.audit_chronicle_customer_id,
        chronicle_service_account=settings.audit_chronicle_service_account,
        chronicle_bearer_token=settings.audit_chronicle_bearer_token,
        chronicle_verify_tls=settings.audit_chronicle_verify_tls,
    )
    from agentmetry.core.audit.alerts import AlertWebhookSink
    from agentmetry.core.audit.sinks import MultiAuditSink

    if settings.audit_alert_webhook_url.strip():
        alert_sink = AlertWebhookSink(
            settings.audit_alert_webhook_url.strip(),
            timeout_seconds=settings.audit_webhook_timeout_seconds,
        )
        if _sink is None:
            _sink = alert_sink
        elif isinstance(_sink, MultiAuditSink):
            _sink._sinks.append(alert_sink)
        else:
            _sink = MultiAuditSink([_sink, alert_sink])

    return _sink


def _schema_payload_fields(payload: dict[str, Any]) -> tuple[str, str, int, str]:
    tool = payload.get("tool") if isinstance(payload.get("tool"), dict) else {}
    server = str(tool.get("server") or payload.get("server") or "")
    fingerprint = str(payload.get("schema_fingerprint") or "")
    try:
        tool_count = int(payload.get("schema_tool_count") or 0)
    except (TypeError, ValueError):
        tool_count = 0
    source = str(payload.get("adapter") or "mcp_proxy")
    return server, fingerprint, tool_count, source


def build_schema_canonical(payload: dict[str, Any], status: str) -> dict[str, Any]:
    """Attestation that a `tools/list` was observed. Names and descriptions stay off it."""
    import uuid
    from datetime import datetime, timezone

    from agentmetry.core.audit.canonical import SCHEMA_VERSION
    from agentmetry.core.audit.identity import identity_fields
    from agentmetry.core.diagnostics.mcp_schema import server_id

    server, fingerprint, tool_count, _source = _schema_payload_fields(payload)
    outcome = "changed" if status == "changed" else "success"
    reason = (
        "MCP tool schema changed; config may be unchanged (rug-pull candidate)"
        if status == "changed"
        else "MCP tool schema observed"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "session_id": str(payload.get("session_id") or ""),
        "correlation_id": str(payload.get("correlation_id") or payload.get("thread_id") or ""),
        "timestamp_utc": str(payload.get("timestamp_utc") or datetime.now(timezone.utc).isoformat()),
        **identity_fields(),
        "source_topic": "agentmetry/mcp_schema",
        "source": {
            "tier": "external",
            "app": str(payload.get("source_app") or "mcp_proxy"),
            "adapter": str(payload.get("adapter") or "mcp_audit_proxy"),
        },
        "initiator": {"actor_type": "system", "trigger": "scheduled", "operator_id": ""},
        "actor": {"type": "system", "id": "agentmetry", "role": "recorder"},
        "action": {"type": "mcp_schema", "outcome": outcome, "reason": reason},
        "agent": {"name": "agentmetry", "skill_id": ""},
        "mcp_schema": {
            "server_id": server_id(server) if server else "",
            "fingerprint": fingerprint,
            "tool_count": tool_count,
            "status": status,
        },
    }


async def _ingest_observed_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Record a `tools/list` fingerprint. Emit a trail event only when it moves.

    Unchanged reconnects would otherwise flood the trail every session start.
    The heartbeat still carries the current digest either way. Sequence
    detection is skipped: this is configuration attestation, not a tool call.

    The store is advanced last, and that ordering is the whole point. Writing
    the new fingerprint first means a failed trail insert leaves it on disk,
    the next observation of the poisoned server reads `same`, and the rug pull
    is never recorded anywhere. Retrying does not help either, because the
    replayed payload takes that same `same` branch, so the spool that rescues
    every other event class is specifically defeated for this one. Committing
    afterwards can instead duplicate an event when two observers race, which
    is a finding an analyst sees twice rather than one they never see.
    """
    from agentmetry.core.audit.trail_db import get_trail_db
    from agentmetry.core.diagnostics.mcp_schema import (
        classify_observation,
        record_observation,
    )

    server, fingerprint, tool_count, source = _schema_payload_fields(payload)
    status = classify_observation(server, fingerprint)
    canonical = build_schema_canonical(payload, status)
    if status == "same":
        # Only the timestamp moves, and nothing alerts on it, so there is
        # nothing to make durable first.
        record_observation(server, fingerprint, tool_count, source=source)
        return canonical
    get_trail_db().insert(canonical)
    sink = _get_sink()
    if sink is None:
        raise RuntimeError("No audit sinks configured")
    await sink.emit(canonical)
    record_observation(server, fingerprint, tool_count, source=source)
    return canonical


async def ingest_external_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate adapter payload, build canonical event, forward to configured sinks."""
    if not settings.audit_ingest_enabled:
        raise ValueError("External audit ingest is disabled")

    if str(payload.get("event_type") or "") == "mcp_schema":
        return await _ingest_observed_schema(payload)

    canonical = build_external_canonical(payload)

    # 1. Durable indexed store (query backend)
    from agentmetry.core.audit.trail_db import get_trail_db
    get_trail_db().insert(canonical)

    # 2. Forward to configured sinks (JSONL file, webhook, Elastic, Splunk)
    sink = _get_sink()
    if sink is None:
        raise RuntimeError("No audit sinks configured")

    await sink.emit(canonical)

    # Emit any inferred approval_response events derived from the stream.
    inferred: list[dict[str, Any]] = []
    for extra_payload in infer_approval_payloads(canonical):
        extra = build_external_canonical(extra_payload)
        inferred.append(extra)
        get_trail_db().insert(extra)
        await sink.emit(extra)

    # Correlate as events arrive. A detection that only surfaces when someone
    # opens the session in the dashboard is not a control — emit it down the
    # same sinks so it reaches the SIEM and the alert webhook.
    pending_detections: list[tuple[Any, dict[str, Any], str, str, str]] = []
    for event in (canonical, *inferred):
        corr = str(event.get("correlation_id") or "")
        host_id = str(event.get("host_id") or "")
        ts = str(event.get("timestamp_utc") or "")
        for detection in (*observe(event), *observe_host(event)):
            pending_detections.append((detection, event, corr, host_id, ts))

    for detection, event, corr, host_id, ts in pending_detections:
        det_event = build_detection_event(detection, event)
        try:
            # The trail insert is the durability guarantee: it raises on a local
            # write failure and the rule stays un-checkpointed, so it re-fires on
            # the next event. Network sinks (webhook/Elastic/Splunk/Loki) swallow
            # their own errors, so a down SIEM does NOT raise here and does not
            # block the checkpoint — forwarding is best-effort, the local trail
            # is the source of truth.
            get_trail_db().insert(det_event)
            await sink.emit(det_event)
        except Exception:
            logger.exception("Failed to emit detection %s", detection.rule_id)
            continue
        if detection.rule_id.startswith("host-"):
            mark_host_detection_emitted(host_id, detection.rule_id, emitted_at=ts)
        else:
            mark_detection_emitted(corr, detection.rule_id, emitted_at=ts)
        logger.warning(
            "DETECTION %s [%s] correlation=%s — %s",
            detection.rule_id,
            detection.severity,
            detection.correlation_id,
            detection.summary,
        )

    logger.info(
        "Ingested external audit event app=%s type=%s correlation=%s",
        (canonical.get("source") or {}).get("app"),
        (canonical.get("action") or {}).get("type"),
        canonical.get("correlation_id"),
    )
    return canonical
