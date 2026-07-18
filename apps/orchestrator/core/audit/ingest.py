"""Ingest external adapter events into Agentmetry sinks (Tier B)."""

from __future__ import annotations

import logging
from typing import Any

from core.audit.detection.live import build_detection_event, mark_detection_emitted, observe
from core.audit.external import build_external_canonical
from core.audit.sinks import build_audit_sinks, parse_sink_modes
from core.config import settings

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
        elastic_url=settings.audit_elastic_url,
        elastic_index=settings.audit_elastic_index,
        elastic_api_key=settings.audit_elastic_api_key,
        elastic_verify_tls=settings.audit_elastic_verify_tls,
        splunk_hec_url=settings.audit_splunk_hec_url,
        splunk_hec_token=settings.audit_splunk_hec_token,
        splunk_index=settings.audit_splunk_index,
        splunk_sourcetype=settings.audit_splunk_sourcetype,
        splunk_verify_tls=settings.audit_splunk_verify_tls,
    )
    from core.audit.alerts import AlertWebhookSink
    from core.audit.sinks import MultiAuditSink

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
async def ingest_external_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate adapter payload, build canonical event, forward to configured sinks."""
    if not settings.audit_ingest_enabled:
        raise ValueError("External audit ingest is disabled")

    canonical = build_external_canonical(payload)

    # 1. Durable indexed store (query backend)
    from core.audit.trail_db import get_trail_db
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
    for event in (canonical, *inferred):
        corr = str(event.get("correlation_id") or "")
        ts = str(event.get("timestamp_utc") or "")
        for detection in observe(event):
            det_event = build_detection_event(detection, event)
            try:
                # Record in the trail first: it is the source of truth and must
                # hold the detection even when forwarding is broken — a
                # misconfigured sink must never make a critical vanish from the
                # record. A re-fire can insert again, but the dashboard dedups
                # detections by rule_id:correlation_id, so any redundant rows
                # written during a sink outage collapse in the UI.
                get_trail_db().insert(det_event)
                await sink.emit(det_event)
            except Exception:
                # Emit (or insert) failed — do NOT checkpoint, so the rule
                # re-fires and re-emits on the next session event instead of the
                # alert being silently lost.
                logger.exception("Failed to emit detection %s", detection.rule_id)
                continue
            # Stored and forwarded — checkpoint. Idempotent, so a recovered emit
            # never double-alerts.
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
