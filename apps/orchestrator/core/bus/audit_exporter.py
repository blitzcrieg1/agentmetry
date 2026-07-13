"""Subscribe to the event bus and forward canonical audit events to configured sinks."""

from __future__ import annotations

import logging

from core.audit.alerts import AlertWebhookSink
from core.audit.canonical import normalize_outbox_row
from core.audit.sinks import MultiAuditSink, build_audit_sinks, parse_sink_modes
from core.bus.bus import EventBus, bus
from core.bus.events import Event, LLM_TOKEN
from core.config import settings

logger = logging.getLogger(__name__)


def event_to_outbox_row(event: Event) -> dict:
    return {
        "seq": event.seq,
        "ts": event.ts,
        "topic": event.topic,
        "session_id": event.session_id,
        "thread_id": event.thread_id,
        "payload": event.payload,
    }


def _describe_sink_targets(modes: set[str]) -> list[str]:
    targets: list[str] = []
    if "file" in modes:
        targets.append(str(settings.audit_export_path))
    if "webhook" in modes and settings.audit_webhook_url.strip():
        targets.append(settings.audit_webhook_url.strip())
    if "elastic" in modes and settings.audit_elastic_url.strip():
        targets.append(f"elastic:{settings.audit_elastic_index}")
    if "splunk" in modes and settings.audit_splunk_hec_url.strip():
        targets.append(f"splunk:{settings.audit_splunk_index}")
    return targets


async def audit_exporter(
    bus_: EventBus = bus,
    *,
    enabled: bool | None = None,
) -> None:
    """Forward normalized bus events to configured sinks (best-effort)."""
    if enabled is None:
        enabled = settings.audit_export_enabled
    if not enabled:
        logger.info("Audit export disabled (BLACKBOX_AUDIT_EXPORT_ENABLED=0)")
        return

    modes = parse_sink_modes(settings.audit_sink)

    sink = build_audit_sinks(
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
    if sink is None and not settings.audit_alert_webhook_url.strip():
        logger.warning(
            "Audit export enabled but no sinks configured "
            "(check BLACKBOX_AUDIT_SINK and backend credentials)"
        )
        return

    # Add Alert Sink if configured
    if settings.audit_alert_webhook_url.strip():
        alert_sink = AlertWebhookSink(
            settings.audit_alert_webhook_url.strip(),
            timeout_seconds=settings.audit_webhook_timeout_seconds,
        )
        if sink is None:
            sink = alert_sink
        elif isinstance(sink, MultiAuditSink):
            sink._sinks.append(alert_sink)
        else:
            sink = MultiAuditSink([sink, alert_sink])

    targets = _describe_sink_targets(modes)
    if settings.audit_alert_webhook_url.strip():
        targets.append(f"alerts:{settings.audit_alert_webhook_url.strip()}")
    logger.info("Audit export sinks → %s", ", ".join(targets))

    sub = bus_.subscribe("audit-export", exclude={LLM_TOKEN})
    try:
        while True:
            event = await sub.get()
            try:
                canonical = normalize_outbox_row(event_to_outbox_row(event))
                if canonical is not None:
                    await sink.emit(canonical)
            except Exception:
                logger.exception("Audit export failed for %s seq=%s", event.topic, event.seq)
    finally:
        bus_.unsubscribe(sub)
