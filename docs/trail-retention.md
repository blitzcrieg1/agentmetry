# Trail rotation and retention

The trail (`audit-forward.jsonl`) is append-only and hash-chained: each record
carries the hash of the one before it, so a deleted, reordered or edited
record breaks `agentmetry verify --trail`. That property is the reason the
trail is evidence, and it is also why "just truncate it" is not an answer when
a pilot asks what happens when it fills the disk. This page is the policy.
Tracking issue: [#101](https://github.com/blitzcrieg1/agentmetry/issues/101).

## What ships: rotation

Rotation archives the active file whole and starts a new one. Nothing is
deleted and no record changes.

```bash
agentmetry trail rotate      # archive the active file now
agentmetry trail segments    # list archived segments and the active file
```

Or rotate automatically once the active file reaches a size:

```ini
AGENTMETRY_TRAIL_ROTATE_BYTES=268435456   # 256 MiB; 0 (the default) = never
```

An archived segment is moved to `<trail>.archive/<stem>.<first seq>-<last seq>.jsonl`
and recorded in `<trail>.archive/segments.json` with its seq range, the hashes
at both ends, its size and a SHA-256 of the file.

The chain does not restart. The next record's `seq` continues and its
`prev_sha256` is the last archived record's hash, because the chain head lives
in the `.chain` sidecar, not in the file. If the sidecar is lost, the head is
recovered from the newest segment rather than reset to genesis.

| Question from #101 | Answer |
|---|---|
| Segment or truncate? | Segment. A new file per rotation, chain continuous across files. |
| What does `verify --trail` cover? | Every segment, from genesis, as one chain. A failure names the segment and the line within it. |
| Anchors across a rotation? | Unaffected. Merkle roots are computed over every record in every segment, so a root anchored before a rotation verifies after it. Tested. |
| Disposition history? | Replayed at boot from the SQLite index, which rotation does not touch. The index backfill reads archived segments too. |
| Dogfood and evidence export? | Read the chain through the same segment-aware reader. A trail that is only archived segments still verifies. |
| The forwarder? | Follows its cursor from the end of one segment into the next, so events appended just before a rotation are still forwarded. |
| Operator command or automatic? | Both. Off by default, so an existing install behaves exactly as before. |

Archived segments are ordinary files: compress or copy them to cold storage
as you would any log, **but keep them where the trail can find them, or
verification fails**. That failure is deliberate: see below.

## What does not ship: retention (deleting old segments)

Deleting a segment removes evidence and changes what the remaining trail can
prove, so it is a decision, not a default. Today, removing an archived segment
makes `verify --trail` fail with a sequence break. That is the correct
behaviour until a pruning mechanism exists that leaves a verifiable record of
what was pruned.

The design, for when a pilot needs it:

1. **Prune only behind an external anchor.** A segment may be deleted only if
   an anchor (`agentmetry anchor`) covering at least its last record has been
   published off-host. The anchor is what still proves the pruned records
   existed and were not altered before deletion.
2. **Leave a checkpoint.** Pruning writes a checkpoint record into
   `segments.json`: the pruned seq range, the last record's hash, the file's
   SHA-256, the anchor that covered it, and who pruned it and when. Verification
   then starts from the checkpoint instead of genesis and reports
   "verified from seq N (records 1 to N-1 pruned under anchor X)", never a
   silent "OK".
3. **Never prune undecided findings.** A segment containing a detection with
   no disposition in the index is not prunable. The dogfood gate and triage
   history depend on those.
4. **Explicit and logged.** `agentmetry trail prune --before <seq> --anchor <id>`,
   an event in the trail recording the prune itself, and no automatic age-based
   deletion.

Merkle roots over a pruned trail are the open problem: a root needs every
leaf. The likely answer is to anchor per segment and verify inclusion against
the segment's anchored root, but it needs a decision on proof format before
code, and it touches the anchor format, which is the kind of change this
project asks about before making.

## Recommended settings for a pilot fleet

- `AGENTMETRY_TRAIL_ROTATE_BYTES=268435456` (256 MiB segments).
- Forward to the SIEM (the SIEM's own retention is then the long-term record).
- Publish anchors off-host on a schedule, so a future prune has something to
  stand on.
- Keep archived segments on the host until a pruning policy is agreed in
  writing with the customer.
