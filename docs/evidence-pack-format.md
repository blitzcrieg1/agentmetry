# Evidence pack format (v1)

BLACKBOX exports a structured JSON audit artifact for a date range:

```powershell
blackbox export --evidence --from 2026-07-01 --to 2026-07-31
blackbox verify vault/30-Archive/exports/evidence-2026-07-01_to_2026-07-31.json
```

Default output: `vault/30-Archive/exports/evidence-<from>_to_<to>.json`

No running orchestrator required — reads `apps/orchestrator/data/events.db` and
`runs.jsonl` directly.

## Schema version 1.0

```json
{
  "meta": {
    "schema_version": "1.0",
    "exported_at": "ISO-8601 UTC",
    "date_from": "YYYY-MM-DD",
    "date_to": "YYYY-MM-DD",
    "vault_path": "/path/to/vault",
    "query_start_ts": "ISO-8601 UTC inclusive lower bound",
    "query_end_ts": "ISO-8601 UTC inclusive upper bound",
    "integrity_sha256": "hex digest of body (see below)"
  },
  "summary": {
    "event_count": 0,
    "run_ledger_rows": 0,
    "approval_gates": 0,
    "approvals_granted": 0,
    "approvals_terminated": 0,
    "approvals_pending": 0,
    "tool_calls": 0,
    "tool_denials": 0,
    "runs_started": 0,
    "runs_failed": 0
  },
  "runs": [],
  "approvals": [],
  "tool_calls": [],
  "events": [],
  "compliance_mapping": {
    "art_12_logging": "...",
    "art_13_transparency": "...",
    "art_14_human_oversight": "...",
    "disclaimer": "..."
  }
}
```

## Integrity

`meta.integrity_sha256` is SHA-256 of the canonical JSON serialization of:

```json
{
  "runs": [...],
  "approvals": [...],
  "tool_calls": [...],
  "events": [...],
  "compliance_mapping": {...},
  "summary": {...}
}
```

Keys sorted, compact separators (`sort_keys=True`, `separators=(",", ":")`).

Verify with `blackbox verify <file>` — recomputes the hash and compares.

## Data sources

| Section | Source |
|---------|--------|
| `events` | `data/events.db` outbox (all bus topics except LLM tokens) |
| `runs` | `data/runs.jsonl` filtered by `ts` |
| `tool_calls` | `events` where `topic` is `run/tool_called` or `run/tool_denied` |
| `approvals` | Reconstructed from `run/approval_required`, `run/completed`, `run/terminated`, plus ledger status rows |

## EU AI Act mapping (informational)

The `compliance_mapping` block explains which sections of the export correspond to
common deployer obligations under Articles 12 (logging), 13 (transparency), and 14
(human oversight). **This is not legal advice or a certification.** Risk
classification depends on your use case — consult qualified counsel.

## v2 (planned)

- PDF/MHTML human-readable summary
- Merkle chain over event seq for third-party verification
- Structured reject reasons + edit diffs in `approvals[]`
- API endpoint `GET /api/v1/audit/export`
