# Claude request and result observations

Optional metadata on new Claude hook events preserves the harness's invocation
ID across request and result observations. It does not independently prove
execution, successful shell completion, delivery to a network destination or
which person operated the reported account.

The additions are optional within canonical schema 1.2.0, like existing account
metadata. Existing fields are not renamed and no new action types are added.
Request and successful-result observations are annotated in place; enabling
the failure hook also records failures that were previously missed. No extra
activity rows are generated solely to correlate observations. Other agents do
not acquire Claude coverage from sharing a hook payload shape.

## Fields

| Field | Meaning and bounds |
| --- | --- |
| `tool.invocation.id` | Exact source `tool_use_id`, when it is a string of 1 to 256 printable ASCII characters without spaces. Invalid or missing IDs are omitted, never trimmed, truncated or replaced. |
| `tool.invocation.phase` | `request` for `PreToolUse`, `result` for the two post-tool events below. |
| `tool.invocation.hook_event` | `PreToolUse`, `PostToolUse` or `PostToolUseFailure`. |
| `tool.invocation.provenance` | Always `harness_reported`. Ingest authentication does not verify the client's report. |
| `tool.result.status` | `reported_success` for `PostToolUse`, `reported_failure` for `PostToolUseFailure`. This describes the hook event's tool-level report, not a numeric process exit code. |
| `tool.result.duration_ms` | Optional strict integer from 0 to 9007199254740991, the largest exactly interoperable JSON integer. No strings, floats, booleans or inferred timing. |
| `tool.result.is_interrupt` | Optional strict boolean on failure observations. False is retained. |
| `tool.result.error_kind` | Constant `interrupted` when the failure reports `is_interrupt: true`; otherwise `tool_failure`. No arbitrary error text. |

Requests have no result block. Results can exist without a valid invocation ID
and then cannot establish an exact invocation relationship. Bad optional
scalars are omitted. Invalid phase, event, provenance or status combinations
drop the new blocks while retaining the legacy event. Unknown keys inside the
new blocks are not copied. HTTP and direct/spool ingest apply the same allowlist.

The normal hashed-argument capture setting applies. Response bodies, raw failure
messages, transcript paths, cwd, process IDs and policy configuration are not
added by this feature. Invocation IDs are client-reported metadata, not a safe
place for secrets. A failure observation does not exclude partial side effects.

## Source coverage

The [Claude hooks reference](https://code.claude.com/docs/en/hooks#pretooluse)
documents tool-use IDs on pre-tool and post-tool inputs. Its
[post-tool sections](https://code.claude.com/docs/en/hooks#posttooluse) describe
an optional execution duration that excludes permission and pre-hook time;
[failure input](https://code.claude.com/docs/en/hooks#posttoolusefailure) also
describes an interruption flag. These mappings were reviewed against the
documentation on November 11, 2026. A minimum compatible Claude release and a
real-session version matrix have not been established.

Newly generated Claude settings include `PostToolUseFailure`. Existing settings
need the normal hook-installation refresh before receiving that event. The
presence of mapper code alone does not establish that an installation has the
hook enabled or that every failed operation will produce an event.

The [permission-request input](https://code.claude.com/docs/en/hooks#permissionrequest)
explicitly lacks a tool-use ID. This feature does not register that event or
manufacture a link for it. Notification hooks are not invocation observations.
No universal numeric process exit-code field or reliable agent/subprocess
identity was established in this source review; neither is parsed from prose.

## Comparing observations

Constrain a comparison to one known recorder/acquisition scope and require
matching source app, source adapter, session ID and exact invocation ID. Tool
identity is an additional consistency check. All key parts must be present.
The current recorder's hostname-based `host_id` is not a globally stable device
identity, so it cannot establish that two acquisitions came from the same host.

For example, these selected tool fields describe two observations of a
synthetic invocation, not a captured or executed session:

```json
[
  {
    "invocation": {
      "id": "toolu_synthetic_001", "phase": "request",
      "hook_event": "PreToolUse", "provenance": "harness_reported"
    }
  },
  {
    "invocation": {
      "id": "toolu_synthetic_001", "phase": "result",
      "hook_event": "PostToolUseFailure", "provenance": "harness_reported"
    },
    "result": {
      "status": "reported_failure", "duration_ms": 0,
      "is_interrupt": false, "error_kind": "tool_failure"
    }
  }
]
```

One request and one result is the simple case. Multiple or conflicting
observations under the same key remain visible and ambiguous. The feature does
not infer attempts, suppress duplicates or provide a join engine. Arrival order
is not execution order; a request without a result remains unresolved. Never
substitute command similarity, argument hashes or a nearby timestamp for an ID.

## Legacy approvals and remaining gaps

Existing action fields keep their legacy semantics. In particular,
`approval_request` on a pre-hook does not prove that a human saw a prompt.
Legacy post-hook outcomes can also reflect the old generic exit/error hints;
the new result status explicitly records the source hook classification.

The existing `*_inferred` adapters synthesize approvals from tool/hash/session
heuristics. They do not carry a native invocation link and must not satisfy an
exact permission-decision step. Preserving new request/result metadata does not
correct that inference or turn it into an observed human decision.

Independent Windows/EDR correlation, stable device identity, agent process
identity, policy revisions and exact permission receipts remain separate work
in [issue #412](https://github.com/blitzcrieg1/agentmetry/issues/412). No Hayabusa
integration, additional default capture, new detection rule or verification
claim is introduced here.
