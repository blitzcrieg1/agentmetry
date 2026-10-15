# Evidence pack format (schema 2.2)

`agentmetry export --evidence` writes a JSON audit artifact for an inclusive
calendar date range. It reads the canonical trail index (`audit.db`), the same
events the dashboard and the SIEM sinks see. No running orchestrator is required.

```text
agentmetry export --evidence --from 2026-07-01 --to 2026-07-31
agentmetry verify path/to/evidence-2026-07-01_to_2026-07-31.json
```

Default path: `vault/30-Archive/exports/evidence-<from>_to_<to>.json` when that
vault directory exists, otherwise `data/exports/` next to the trail.

## Top-level keys

`meta`, `events`, `tool_calls`, `approvals`, `detections`, `dispositions`,
`controls`, `compliance_mapping`, `summary`.

## `meta`

| Field | Meaning |
| --- | --- |
| `schema_version` | `2.2` on packs this version writes |
| `producer` | `agentmetry/<version>`, the build that wrote the pack |
| `exported_at` | UTC timestamp of the export |
| `date_from`, `date_to` | Inclusive calendar dates the pack claims to cover |
| `query_start_ts`, `query_end_ts` | UTC bounds used to read the trail |
| `source` | `audit_trail` |
| `raw_events_included` | Whether `events` holds the raw records |
| `events_truncated` | True when the window held more events than one export reads (200,000). The pack is then a prefix of the window, not the whole period |
| `trail_chain` | Chain head the pack was drawn against (`head_seq`, `head_sha256`, `verified`, line counts) |
| `integrity_sha256` | Digest defined below. Not itself an input to the digest |

## Integrity

For schema 2.2 and later, `meta.integrity_sha256` is the SHA-256 of the
canonical JSON of `meta` (with `integrity_sha256` removed) plus every body
section. Canonical means keys sorted and compact separators, the same
serialization `json.dumps(..., sort_keys=True, separators=(",", ":"))` produces.

`agentmetry verify <file>` recomputes that digest. Editing the date range, the
producer, the trail-chain binding, or any body section fails the check.

Packs whose `schema_version` is below `2.2`, including `2.1`, are verified the
old way: the digest covers the body sections only, not `meta`. Those packs stay
verifiable. Their date range is not protected. Re-export if you need the
stronger check.

The digest is an integrity check on the file. It is not a signature. Someone
who rewrites the pack and the digest together still needs the trail chain and
an external anchor (`agentmetry anchor`, `agentmetry verify --trail`) before a
third party should trust the contents.

## Where each section comes from

| Section | Source |
| --- | --- |
| `events` | `audit.db`, events whose `timestamp_utc` falls inside the query bounds |
| `tool_calls`, `approvals`, `detections` | Derived from those events |
| `dispositions` | Triage decisions recorded on the trail during the window. The disposition currently in force is also stamped on each detection, including decisions made outside the window |
| `controls` | DLP and tool-policy manifest hashes and modes in force at export time. This is the configuration at export, not a history of every change inside the window |
| `compliance_mapping` | Static explanatory text, including what the pack does not cover |
| `summary` | Counts over the sections above |

This pack is an operator-generated artifact. It is not legal advice and it is
not a certification.
