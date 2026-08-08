# Anchoring the trail

## What the hash chain proves, and where it stops

Every record in the JSONL trail is chained: `record_sha256 = SHA-256(prev_sha256 + canonical_event_json)`, with the head kept in a `.chain` sidecar. `agentmetry verify --trail` walks the file and confirms every link.

That catches accidental corruption, a truncated write, a partial disk failure, and a naive edit. Those are real and they happen.

It does not catch an attacker with write access to the data directory. Such an attacker edits an event, recomputes every hash after it, rewrites the sidecar head, and hands you a file that verifies perfectly. Every input to the verification lives on the machine under their control.

This is not a defect in the chain. It is the ceiling of what any self-contained file can prove about itself, and it is why this documentation says **hash-chained and verifiable, with optional external anchoring** rather than "tamper-proof".

Anchoring raises the ceiling.

## The idea

Publish a small commitment somewhere the local attacker does not control:

```
tree_size = 5400
root      = ec330c468169a975...
```

The root is the RFC 6962 Merkle root over the first 5400 record hashes. Change any one of those records and the root changes. So a published root from last Tuesday is a claim the host can no longer edit its way out of.

The trail itself never leaves. The root discloses nothing about the events: it is 32 bytes of hash output over hashes. That is what makes it safe to publish to a third party at all.

## Producing a checkpoint

```bash
agentmetry anchor data/audit-forward.jsonl
```

Appends to `data/audit-forward.jsonl.anchors.jsonl` and prints a one-line statement:

```
agentmetry-anchor v1 alg=rfc6962-sha256 trail=audit-forward.jsonl tree_size=5400 root=ec33... head_seq=5400 head=f190... host=home-lab at=2026-08-08T09:12:03Z
```

To produce the statement without recording it locally, for handing to an external sink:

```bash
agentmetry anchor data/audit-forward.jsonl --print
```

## The shipped sink is local, and that is a limitation

`FileAnchorSink` writes to a file on the same disk as the trail. On its own it adds nearly nothing: an attacker who can rewrite the trail can rewrite the anchor log beside it. `agentmetry verify --trail` says so in as many words rather than showing a green check.

It ships because it makes the interface real, and because the file becomes worth something the moment a copy leaves the host by a route the attacker does not mediate.

## Attaching a real anchor

Pick one. All three defend against the same thing (a host that rewrites its own history) with different trust assumptions, and none of them require the trail to leave your infrastructure.

### 1. A git repository with a remote

The cheapest option that works, and the one to start with.

```bash
agentmetry anchor data/agentmetry-trail.jsonl \
  --anchors ../agentmetry-anchors/home-lab/agentmetry-trail.anchors.jsonl
cd ../agentmetry-anchors
git add . && git commit -m "anchor: tree_size 5938" && git push
```

The forge holds commit history the workstation cannot rewrite. If that machine is later compromised, the pushed commits still say what the root was.

**Protect the branch, or you have not anchored anything.** The threat model here is a compromised developer machine, and that machine holds the credentials that can push to the repository. Without protection an attacker force-pushes the inconvenient history away and the anchor was decorative:

```bash
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input - <<'JSON'
{"required_status_checks":null,"enforce_admins":true,
 "required_pull_request_reviews":null,"restrictions":null,
 "allow_force_pushes":false,"allow_deletions":false}
JSON
```

`enforce_admins` is the field that matters. Without it the repository owner is exempt, and the attacker holding the workstation's token *is* the owner.

Two constraints worth knowing before you pick a repository:

- On GitHub, branch protection is **free on public repositories and requires a paid plan on private ones**. An anchor log contains roots, counts and timestamps, never event content, so publishing it is usually the right trade. But it is a disclosure decision, so make it deliberately.
- Verify the protection by trying to defeat it. A force-push should come back `remote rejected ... cannot force-push to this branch`.

On Windows, [`scripts/publish_anchor.ps1`](../scripts/publish_anchor.ps1) does the whole loop (checkpoint, commit, push, verify against the pushed copy) and exits quietly when no new records have arrived. Register it on a schedule so the unanchored window stays small.

### 2. An RFC 3161 timestamp authority

A TSA signs "this digest existed at this time". That is exactly the property a rewritten trail cannot manufacture, because the attacker cannot obtain a receipt dated before the edit.

```bash
agentmetry anchor data/audit-forward.jsonl --print > checkpoint.txt
openssl ts -query -data checkpoint.txt -sha256 -cert -out checkpoint.tsq
curl -H "Content-Type: application/timestamp-query" \
     --data-binary @checkpoint.tsq https://freetsa.org/tsr -o checkpoint.tsr
```

Check it later:

```bash
openssl ts -verify -data checkpoint.txt -in checkpoint.tsr -CAfile tsa-ca.pem
```

Keep `checkpoint.txt` and `checkpoint.tsr` together. Many organisations already run an internal TSA for code signing; if yours does, use it instead of a public one.

### 3. A transparency log or internal append-only store

If you already run Sigstore, an internal Trillian instance, an S3 bucket with Object Lock, or a WORM appliance, the checkpoint statement is a small enough payload to put in any of them.

A note on Sigstore specifically: Rekor v1 is in maintenance mode and Rekor v2 (tile-based, Trillian-Tessera) is where active development is. Anything you build against v1 today should assume a migration.

## Checking coverage

```bash
agentmetry verify --trail data/agentmetry-trail.jsonl \
  --anchors ../agentmetry-anchors/home-lab/agentmetry-trail.anchors.jsonl
```

**`--anchors` is what makes this check worth running.** Against the anchor log sitting next to the trail, whoever rewrote one rewrote the other, and the comparison proves only that a file agrees with itself. Pointed at a copy on a protected remote, the same comparison is the one thing an attacker on this host could not forge.

```
OK — 5691 chained line(s) verified
  lines: 5691 total, 5691 chained, 0 legacy
  head: seq 5691, sha256 26864cdd...
  merkle root: c19b7814...
  tree size: 5691 (rfc6962-sha256)
  anchors: 3 checkpoint(s)
    records 1-5400 anchored
    records 5401-5691 unanchored (291 newer) — chain-verified only, not a weaker chain but a weaker guarantee
```

**Anchored is a range, not a boolean.** A checkpoint covers the records that existed when it was published and says nothing about what was appended afterwards. Reporting the whole trail as anchored because one checkpoint exists would overstate it, so the tail is named for what it is.

An unanchored range is not a failure. It is the normal state of a running recorder, and scoring it red would make the check cry wolf until somebody turns it off.

When a checkpoint does not match:

```
    TAMPERING — root at size 5400 is 04cbfa36... but ec330c46... was anchored on
                2026-08-08T09:12:03Z — a record below that point was altered
FAILED — the chain is internally consistent but contradicts a published anchor.
         The file was rewritten.
```

The two failure modes read differently on purpose. A root mismatch means history was edited. A trail shorter than a checkpoint claimed means records were deleted. A responder who cannot tell them apart cannot scope the incident.

## Writing your own sink

`AnchorSink` is a one-method protocol:

```python
class AnchorSink(Protocol):
    name: str
    def publish(self, checkpoint: Checkpoint) -> AnchorReceipt: ...
```

It takes the whole `Checkpoint`, not just the root, because a sink that records only a bare hash cannot say which trail it covered or how much of it, and a commitment you cannot locate afterwards is not a commitment.

This repository ships exactly one implementation and documents the rest. Choosing an anchor means choosing who you trust to hold history: a forge, a timestamp authority, a public log, your own WORM storage. That is the operator's decision, and picking one on your behalf would be making it for you.

## What to tell an auditor

> The trail is hash-chained with SHA-256 and every record is verifiable against its predecessor. The chain detects corruption, truncation, and modification by anything short of an attacker with write access to the host. For that threat model we publish a Merkle root to *[your anchor]* every *[interval]*; any modification to a record below the last published root is detectable by recomputation. Records appended since the last checkpoint carry the chain guarantee only.

That last sentence is the one to keep. It is shorter than the alternative and it is the one a technical evaluator is checking for.
