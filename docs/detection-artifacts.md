# Detection artifacts

New live detection events can include `detection.artifacts`, an additive field
in canonical schema `1.2.0`. It gives downstream consumers the available
tool-boundary observations behind a finding without requiring a second lookup.
This implements the [Tenzir integration request](https://github.com/tenzir/library/pull/225#issuecomment-6762548015).
It does not change a rule, severity, emission checkpoint or capture setting.

## Version 1 contract

| Field | Meaning |
| --- | --- |
| `version` | Integer `1`, versioning this block separately from the canonical schema |
| `items` | Selected snapshots, in `detection.event_ids` order, with repeated references collapsed |
| `referenced_count` | Number of unique referenced event IDs |
| `unavailable_count` | Referenced rows missing from the bounded detector window, ambiguous because their ID occurs more than once, outside the finding's scope, or with an empty/overlong ID |
| `omitted_count` | Available rows excluded by the item or serialized byte limit |
| `truncated` | True if rows were excluded by a limit or any included item has `omitted_fields`. Missing rows alone do not set this flag |

`referenced_count` equals the number of items plus `unavailable_count` plus
`omitted_count`. Unavailable is unknown, not an assertion that nothing happened.
The original `detection.event_ids` are unchanged.

An item copies only these nonempty string fields when present:

- `event_id`, `correlation_id`, `timestamp_utc`.
- `source.app`, `source.adapter`.
- `action.type`, `action.outcome`, `action.reason`.
- `tool.name`, `tool.qualified`, `tool.server`, `tool.command`.
- `tool.arguments.file_path`, `path`, `target_file`, `url`.
- `gated_action.tool`, `gated_action.server`.

No arbitrary arguments, nested objects, outputs, account blocks, environment,
input hashes or process IDs are copied. The allowlist is intentional: other
captured fields remain on the original event.

Tool/server names are normally available with hashed-only capture. Command and
argument fields appear only if present on the canonical source event, for
example through an existing command-logging or full-argument opt-in. This code
does not turn either setting on or recover plaintext from traits or hashes.
An adapter can supply fewer fields; their absence makes no coverage claim.

## Privacy and bounds

The block uses the same best-effort secret scrubber as canonical ingestion.
This cannot recognize every secret. Even selected paths and captured commands
can contain sensitive text, so the block is not guaranteed secret-free.
An absolute HTTP(S) `tool.arguments.url` has userinfo, query and fragment
removed. Its remaining text is scrubbed. Other URL shapes and malformed URLs
are omitted. This URL normalization applies to that argument field only,
not to arbitrary URL text inside a captured command.

An item records changed field names in `sanitized_fields`. Overlong strings
and invalid/unsupported URL arguments have their field names recorded in
`omitted_fields`; their partial contents are not substituted as exact evidence.
Empty or non-string values are simply absent.

Limits are 32 items and 64 KiB for `json.dumps(block)` encoded as UTF-8 using
Python's default ASCII escaping and separators. A small internal reserve keeps
the final counters within that limit. Commands and action reasons allow 4,096
characters, path and URL arguments 2,048, and other strings 512. These are
checked before and after redaction. They are export bounds, not detection
thresholds. Consumers reserializing the object
with different formatting may produce a different byte count.

## Provenance and limits

The live observer selects only cited rows from the same bounded window that
produced the detection. There are no extra database lookups or filesystem
reads. Session findings require the same correlation, host and fleet. Host
findings allow several correlations on the same host/fleet, with each source
correlation retained on its item. Duplicate IDs are considered ambiguous even
if the rows look identical.

An item is a snapshot of a reported event, not proof of execution. In particular,
`denied` stays denied, and an approval with an `inferred:` reason stays inferred.
A gate-only event has `gated_action`, not an invented tool invocation. A tool
call's reported `success` has only the semantics of its adapter. No PID, OS user,
file-content hash or verified identity is inferred from an event ID or argument
hash.

Previously stored findings are not backfilled. The pure detector and the API
that recomputes findings on read can return no `artifacts` field. New live
findings carry the block through the canonical SQLite record and file sink.
Canonical consumers must tolerate its absence and unknown additive fields.
Non-canonical export adapters may omit it.

This block is not an OCSF evidence object. OCSF 1.9 requires at least one of its
[supported evidence attributes](https://github.com/ocsf/ocsf-schema/blob/856d462bd20dc46cc1ffed2dfffe3b91ef0fbeba/objects/evidences.json),
such as `actor`, `api`, `file` or `url`. An AI agent alone does not meet that
constraint; an actor is one option, not a universal requirement. Promoting
individual artifacts requires a separate Tenzir update and schema validation.
The finding's triggering actor must not be assumed to be the actor for every
cited event, especially across sessions. No live Tenzir or Wazuh backend
validation is claimed here.

See the [synthetic hashed-only finding](./examples/detection-artifacts-v1.json).
