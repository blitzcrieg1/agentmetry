# Microsoft Sentinel

Agentmetry forwards its trail to Microsoft Sentinel through the Azure Monitor
**Logs Ingestion API**, into a custom table `Agentmetry_CL`. Like every network
sink, it is fed by the trail forwarder: batches, a cursor, and retries with
backoff while Azure or Entra is unreachable, so an outage delays events rather
than losing them. Analytics rules: [detections-sentinel.md](./detections-sentinel.md).

Not yet validated against a live workspace by the maintainers. The request
shape follows Microsoft's Logs Ingestion API reference; the tests check the
wire format against that reference, not against Azure.

## 1. Table and data collection rule

Create the custom table `Agentmetry_CL` in the workspace Sentinel uses, and a
data collection rule (DCR) with direct ingestion. The DCR's stream declaration
must list exactly these columns: a column the DCR does not declare is dropped
without an error. (A test in this repository checks this block against the
code that builds the records.)

```json
{
  "location": "<workspace region>",
  "kind": "Direct",
  "properties": {
    "streamDeclarations": {
      "Custom-Agentmetry_CL": {
        "columns": [
          { "name": "TimeGenerated", "type": "datetime" },
          { "name": "EventId", "type": "string" },
          { "name": "SchemaVersion", "type": "string" },
          { "name": "ActionType", "type": "string" },
          { "name": "ActionOutcome", "type": "string" },
          { "name": "ActionReason", "type": "string" },
          { "name": "CorrelationId", "type": "string" },
          { "name": "SessionId", "type": "string" },
          { "name": "HostId", "type": "string" },
          { "name": "FleetId", "type": "string" },
          { "name": "OperatorId", "type": "string" },
          { "name": "SourceApp", "type": "string" },
          { "name": "SourceTier", "type": "string" },
          { "name": "ToolQualified", "type": "string" },
          { "name": "ToolInputHash", "type": "string" },
          { "name": "InputRedaction", "type": "string" },
          { "name": "RuleId", "type": "string" },
          { "name": "Severity", "type": "string" },
          { "name": "TacticIds", "type": "dynamic" },
          { "name": "TechniqueIds", "type": "dynamic" },
          { "name": "Event", "type": "dynamic" }
        ]
      }
    },
    "destinations": {
      "logAnalytics": [
        { "workspaceResourceId": "<workspace resource id>", "name": "sentinel" }
      ]
    },
    "dataFlows": [
      {
        "streams": ["Custom-Agentmetry_CL"],
        "destinations": ["sentinel"],
        "transformKql": "source",
        "outputStream": "Custom-Agentmetry_CL"
      }
    ]
  }
}
```

`TenantId` is a reserved column name in Log Analytics, which is why the fleet
is `FleetId`. The whole canonical event is in `Event` (dynamic), so any field
the typed columns do not promote is still reachable as, for example,
`Event.heartbeat.hooks_uncovered`.

Note the DCR's **logs ingestion endpoint** (JSON view of the DCR) and its
**immutable ID** (`dcr-...`, on the Overview page). A data collection endpoint
(DCE) is only needed with private link or an older DCR without `"kind": "Direct"`.

## 2. App registration

Register an Entra application, create a client secret, and on the DCR grant it
the **Monitoring Metrics Publisher** role (Access control (IAM) on the DCR).
That role on that DCR is all it needs.

## 3. Agentmetry

```ini
AGENTMETRY_AUDIT_SINK=file,sentinel
AGENTMETRY_AUDIT_SENTINEL_ENDPOINT=https://<dcr-or-dce>.<region>-1.ingest.monitor.azure.com
AGENTMETRY_AUDIT_SENTINEL_DCR_ID=dcr-00000000000000000000000000000000
AGENTMETRY_AUDIT_SENTINEL_STREAM=Custom-Agentmetry_CL
AGENTMETRY_AUDIT_SENTINEL_TENANT_ID=<directory (tenant) id>
AGENTMETRY_AUDIT_SENTINEL_CLIENT_ID=<application (client) id>
AGENTMETRY_AUDIT_SENTINEL_CLIENT_SECRET=<client secret value>
```

On an MSI host, put these in `%ProgramData%\Agentmetry\.env`, which only
administrators and the service can read. The sink is forwarder-only
(`AGENTMETRY_AUDIT_FORWARDER=1`, the default).

`GET /api/v1/audit/status` shows the `sentinel` destination's last forwarded
`seq` and how long it has been failing. A wrong secret shows up there as a
failing token request, and events wait in the trail until it is fixed.

## 4. Check it arrived

```kusto
Agentmetry_CL
| where TimeGenerated > ago(1h)
| summarize events = count() by ActionType, SourceApp, HostId
```
