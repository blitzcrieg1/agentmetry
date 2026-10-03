"""Canonical event -> Microsoft Sentinel (Log Analytics) record.

Sent through the Azure Monitor Logs Ingestion API into a custom table,
`Agentmetry_CL` by default (pilot hardening item 25). The columns below are the
stream declaration in docs/integrations/sentinel.md; a test checks the two
agree, because a record column the DCR does not declare is silently dropped.

The fields an analytics rule filters on are promoted to typed columns. The
whole canonical event also travels in `Event` (dynamic), so nothing is lost and
a KQL query can reach any nested field as `Event.heartbeat.hooks_uncovered`.
`TenantId` is reserved in Log Analytics, which is why the fleet is `FleetId`.
"""

from __future__ import annotations

from typing import Any

#: Column name -> Log Analytics type. Order is the table's column order.
COLUMNS: dict[str, str] = {
    "TimeGenerated": "datetime",
    "EventId": "string",
    "SchemaVersion": "string",
    "ActionType": "string",
    "ActionOutcome": "string",
    "ActionReason": "string",
    "CorrelationId": "string",
    "SessionId": "string",
    "HostId": "string",
    "FleetId": "string",
    "OperatorId": "string",
    "SourceApp": "string",
    "SourceTier": "string",
    "ToolQualified": "string",
    "ToolInputHash": "string",
    "InputRedaction": "string",
    "RuleId": "string",
    "Severity": "string",
    "TacticIds": "dynamic",
    "TechniqueIds": "dynamic",
    "Event": "dynamic",
}


def _d(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def canonical_to_sentinel_record(canonical: dict[str, Any]) -> dict[str, Any]:
    action = _d(canonical.get("action"))
    tool = _d(canonical.get("tool"))
    source = _d(canonical.get("source"))
    actor = _d(canonical.get("actor"))
    detection = _d(canonical.get("detection"))
    mitre = _d(tool.get("mitre"))
    tactics = detection.get("tactic_ids") or ([mitre["tactic_id"]] if mitre.get("tactic_id") else [])
    techniques = detection.get("technique_ids") or ([mitre["technique_id"]] if mitre.get("technique_id") else [])
    return {
        "TimeGenerated": str(canonical.get("timestamp_utc") or ""),
        "EventId": str(canonical.get("event_id") or ""),
        "SchemaVersion": str(canonical.get("schema_version") or ""),
        "ActionType": str(action.get("type") or ""),
        "ActionOutcome": str(action.get("outcome") or ""),
        "ActionReason": str(action.get("reason") or ""),
        "CorrelationId": str(canonical.get("correlation_id") or ""),
        "SessionId": str(canonical.get("session_id") or ""),
        "HostId": str(canonical.get("host_id") or ""),
        "FleetId": str(canonical.get("fleet_id") or ""),
        "OperatorId": str(actor.get("id") or ""),
        "SourceApp": str(source.get("app") or ""),
        "SourceTier": str(source.get("tier") or ""),
        "ToolQualified": str(tool.get("qualified") or ""),
        "ToolInputHash": str(tool.get("input_hash") or ""),
        "InputRedaction": str(tool.get("input_redaction") or ""),
        "RuleId": str(detection.get("rule_id") or ""),
        "Severity": str(detection.get("severity") or ""),
        "TacticIds": list(tactics),
        "TechniqueIds": list(techniques),
        "Event": canonical,
    }
