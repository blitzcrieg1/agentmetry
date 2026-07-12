# AgentAudit — `blackbox export --audit` hash-chain spec

**For Cursor.** Implementation spec, not code. Do **not** write Python from this unless the operator explicitly asks — this is the design contract to build against.

**Status:** not built. This is the Week 5 code item (#6). Blocked until the [dogfood checklist](./agentaudit-dogfood-checklist.md) is GREEN so the export is validated against the same event shapes it reads.

---

## Goal

A CLI that exports a **range** of canonical audit events from the SQLite outbox (`events.db`) as JSONL, with an **optional tamper-evident hash chain** so a recipient (IRT, auditor) can prove the exported sequence wasn't altered or truncated.

This is distinct from the two existing artifacts — do not merge them:

| Artifact | What it is | Keep separate because |
|----------|-----------|------------------------|
| `audit-forward.jsonl` (live) | Append-only stream the sinks emit in real time | Never rewritten; not range-scoped |
| `blackbox export --evidence` (existing) | Batch compliance pack, its own JSON format + SHA-256 | Broader payload (runs, approvals, SOP hashes, drivers snapshot) |
| **`blackbox export --audit` (new)** | Range-scoped canonical JSONL + optional per-event hash chain | The forensic hand-off artifact — one IR investigation's events, provably intact |

---

## CLI signature

```
blackbox export --audit [--from DATE] [--to DATE] [--thread-id ID] [--chain] [--out PATH]
```

| Flag | Meaning |
|------|---------|
| `--from DATE` / `--to DATE` | Inclusive UTC range on `timestamp_utc` (ISO-8601 or `YYYY-MM-DD`). Omit both = all events. |
| `--thread-id ID` | Filter to one `correlation_id`. Combinable with the range. |
| `--chain` | Also emit the sidecar hash-chain manifest (below). Without it, plain JSONL only. |
| `--out PATH` | Output path base. Default: `vault/30-Archive/exports/audit-<stamp>.jsonl`. |

Exit `0` on success including empty result; non-zero only on real errors (bad date, unreadable `events.db`).

---

## Output format

### Event file (always)

`audit-<stamp>.jsonl` — one canonical event per line, **byte-identical to the canonical form** the live forwarder uses (same `core/audit/canonical.py` normalizer). Ordered by `seq` ascending. No new fields injected into the events themselves.

### Chain manifest (only with `--chain`)

A **sidecar** file `audit-<stamp>.chain.json` — the events stay untouched; the chain lives beside them. This is what keeps the change **additive** (see compound-bet note).

```json
{
  "schema_version": "1.0.0",
  "chain_algo": "sha256-jcs",
  "created_utc": "2026-07-12T09:20:00+00:00",
  "event_count": 128,
  "range": {"from": "...", "to": "...", "thread_id": null},
  "root_hash": "<sha256 of the final link>",
  "links": [
    {"seq": 1, "event_id": "...", "event_hash": "<h1>", "chain_hash": "<c1>"},
    {"seq": 2, "event_id": "...", "event_hash": "<h2>", "chain_hash": "<c2>"}
  ]
}
```

### Chain algorithm

For each event in `seq` order:
1. **Canonicalize** the event JSON with **JCS (RFC 8785)** — deterministic key ordering, no whitespace. (JCS is the AAT/structured-log direction; do not roll a custom serializer.)
2. `event_hash = SHA-256(JCS(event))`
3. `chain_hash = SHA-256(prev_chain_hash ‖ event_hash)`, where `prev_chain_hash` is the empty string for `seq[0]`.
4. `root_hash` = the last `chain_hash`.

Any inserted, removed, reordered, or byte-altered event breaks `chain_hash` at that link and every link after it — so truncation and tampering both surface.

### Verification (companion, same PR)

```
blackbox verify --audit <audit-*.jsonl> [--chain <audit-*.chain.json>]
```

Recomputes the chain from the event file and compares to the manifest. Prints the first `seq` where they diverge, or `OK <root_hash>`. If `--chain` omitted and no sidecar found, verify the JSONL is well-formed canonical only (no integrity claim).

---

## Additive guarantee (compound-bet red line #4)

- **Do not rename or remove any existing canonical field.** The exported events must be the same shape the live sink emits.
- The hash chain is a **sidecar**, never inline in the event objects — so existing consumers (Loki, Elastic, Splunk, the Sigma pack) are unaffected.
- `chain_algo` is versioned in the manifest so a future algorithm change is additive, not breaking.
- Commit message includes the **"compound preserved?"** note per the red-lines rule.

---

## Acceptance tests

1. **Range filter** — events outside `[--from, --to]` are excluded; boundary events (== from, == to) are included.
2. **Thread filter** — `--thread-id X` yields only events with `correlation_id == X`; combined with a range, both apply.
3. **Round-trip fidelity** — every exported line parses as canonical schema v1.0.0 and equals the `events.db` source event (no field added/dropped/renamed).
4. **Chain determinism** — exporting the same range twice yields identical `root_hash`.
5. **Tamper detection** — flip one byte in one exported event line; `verify --audit` fails and names that `seq`.
6. **Truncation detection** — delete the last event line; `verify` fails (manifest `event_count`/`root_hash` mismatch).
7. **Empty range** — a range with no events writes an empty `.jsonl`, a manifest with `event_count: 0` and a defined empty-chain `root_hash`, exits `0`.
8. **No-chain default** — without `--chain`, no sidecar is written and the JSONL is still valid canonical.
9. **Schema-stability guard** — a test asserting the exported event key set == the live canonical key set (fails loudly if someone adds an inline chain field later).

---

## Out of scope (do not build now)

- Signing the manifest with an external key (PKI / cosign) — v2; SHA-256 chain is the v1.1 bar.
- Merkle tree / inclusion proofs — the linear chain is enough for one-investigation hand-off.
- Streaming chain into the live `audit-forward.jsonl` — the live stream stays plain; chaining is an export-time concern.
- Any change to how the sinks or `canonical.py` emit live events.

---

## Why this shape

An IR hand-off needs one file you can email and one manifest that proves it's whole. Keeping the chain in a sidecar means the JSONL still drops straight into Loki/Elastic/Splunk and still matches the Sigma pack, while the manifest gives an auditor a single `root_hash` to check. That is the whole point of the flight-recorder positioning: the record is portable, inspectable, and provably intact — without a vendor in the verification path.

---

*Companion: [event schema](./agent-audit-event-schema.md) · [dogfood checklist](./agentaudit-dogfood-checklist.md) (run GREEN before building) · [Sigma pack](./integrations/sigma/README.md) (consumes the same JSONL).*
