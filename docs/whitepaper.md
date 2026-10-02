# Agentmetry: recording what AI coding agents actually did

**A technical whitepaper.** Version 0.7.0, 2026-08-27.

Every number in this document comes from a command in the repository. Where a
claim cannot be reproduced, it is not made.

---

## 1. The problem

An AI coding agent is given a shell, a filesystem, a git remote, and a set of
MCP tools. It then acts, hundreds of times an hour, mostly unattended.

Ask the obvious question afterwards, "what did it do", and there is usually no
answer. The agent's own transcript is a conversation, not a record of effects.
The IDE keeps no durable log. Endpoint detection sees a process tree in which
`node` spawned `bash`, which is true and useless, because that is what a coding
agent looks like when it is working correctly.

The gap is not that agents are unmonitored in general. It is that **the tool
boundary, where intent becomes effect, is not recorded anywhere by default**.

That matters more than it used to, because the boundary is now an attack
surface. The MCPTox benchmark evaluated 20 LLM agents against 353 authentic
tools across 45 live MCP servers and found injected instructions were followed
36.5% of the time on average, peaking at 72.8%, with the best refusal rate under
3%. More capable models did worse, because the attack exploits the ability that
makes them useful.

---

## 2. Where to observe

Three places are available. Two of them are wrong.

**The model.** Prompts and completions are the richest signal and the worst
evidence. They tell you what was said, not what happened, and they are enormous,
sensitive, and full of the customer's source code. A recorder that stores them
is a data breach waiting for a misconfiguration.

**The process.** Kernel or EDR telemetry is durable and tamper-resistant, and it
has no idea which agent session a `write()` belongs to, or that the file being
read is a credential the agent was told to fetch. Correlation is the whole
question and the process layer cannot answer it.

**The tool boundary.** Between the two. An agent calls `Read` with a path, or
`Bash` with a command, or an MCP tool with arguments. Every call is attributable
to a session, ordered in time, and small.

Agentmetry observes the tool boundary, through two capture paths:

- **IDE lifecycle hooks** for Claude Code, Cursor, Codex, Antigravity, Qwen and
  Kimi. A hook fires before and after each tool call.
- **An MCP audit proxy** that wraps any stdio MCP server and sees every
  `tools/call`, every `tools/list`, and the `initialize` handshake.

Both normalise into one canonical event schema, currently **1.2.0**, which
changes additively so a consumer written against 1.1.0 keeps parsing.

---

## 3. Why sequences

A single tool call is almost never a finding.

Reading `~/.aws/credentials` is what deployment scripts do. Fetching a URL is
what package installers do. Running `python -c` is what everyone does. Alerting
on any of them individually produces a queue nobody reads, which is the failure
mode that makes most detection products worthless in practice.

The finding is the **order**. A credential read, then an outbound request to a
host that is not in the project, inside one session, in that sequence, is a
different thing from either half.

So the detection unit is an ordered session, and the engine ships **14 published
sequence rules**, plus one held back as experimental (section 9).

Ordering is explicit: events are sorted by timestamp, with a deterministic
tie-break, because "did A happen before B" is the question every rule asks and
answering it by hash ordering would be answering at random.

Each rule carries MITRE ATT&CK tactic and technique ids. Rules describing
something done **to or through the agent** rather than to the host also carry
MITRE ATLAS ids, verified against **ATLAS 2026.07, format version 6.0.0**. The
split is deliberate: reading a private key is `T1552.001` regardless of who did
it, but an MCP server silently changing its advertised tools has no honest
ATT&CK id, and ATLAS names it exactly.

---

## 4. Traits: detection without keeping the evidence

The rules need to know that a command downloaded and executed remote code. The
privacy design says command text never leaves the machine, and by default
arguments are hashed inside the hook process.

Those two requirements are in direct conflict, and the first implementation lost
the fight: every command-regex rule was blind on real captured traffic, because
the tests injected a `command` field that production events did not have.

The resolution is to **classify where the plaintext is still visible**. The hook
process, which already has the command in order to hash it, runs a fixed set of
regexes first and emits category labels. There are **17 traits**, including
`CREDENTIAL_PATH`, `PIPE_TO_SHELL`, `STAGING_FETCH`, `GIT_EXFIL`, `ENCODED_CMD`
and `DOWNLOAD_EXEC`.

The rules then match on labels rather than text. No command ever leaves the
machine, and detection still works on real traffic.

One consequence worth stating: the trait module is imported by the hook client
through a path mechanism, so it must stay dependency-free. It uses `re` and
nothing else. Rules and hook cannot drift apart because they share one file.

---

## 5. The trail

Events are appended to a JSONL file the operator owns. Each line is an envelope:

```json
{"trail": {"v": 1, "seq": 42, "prev_sha256": "...", "record_sha256": "..."},
 "event": { ... }}
```

`agentmetry verify --trail` walks the chain and reports corruption, truncation,
and in-place edits.

### The ceiling, stated plainly

A hash chain in a file proves nothing against an attacker who can write to that
file. They can edit an event, recompute every hash after it, rewrite the
sidecar, and produce a file that verifies. Every input to the verifier lives
inside that blast radius.

This is not a defect in the implementation. It is the ceiling of what a
self-contained file can prove about itself, and pretending otherwise is how
audit tooling loses credibility with the one reader who checks.

### Raising it

Two mechanisms, both additive.

**Merkle inclusion proofs.** The linear chain answers "has this file been
altered". It cannot answer "did this specific event happen" without disclosing
the whole file, since every hash depends on its predecessor. A Merkle tree over
the same `record_sha256` values answers it in O(log n) hashes, so one tool call
can be proved without handing over a month of unrelated work. Leaves are hashes
the chain already computes, so every trail ever written is compatible and
nothing needs migrating.

**External anchoring.** Publish `(tree_size, root_sha256)` somewhere the audited
machine cannot rewrite: a git commit, an RFC 3161 timestamp authority, WORM
storage. Everything before an anchor is then fixed by something outside the
blast radius.

### Tamper-evident is not attributable

A trail proves it has not been edited since it was anchored. It does not prove
which machine produced it. Per-host signing keys are the answer and they are
enterprise scope, not shipped in the open sensor. The README says so, because
four separate reviews of this project repeated an overstatement of the weakness
back to us before anyone read the code, and the correction was to be *less*
alarming than the reviews, not more.

---

## 6. MCP schema fingerprinting

An MCP server hands the model a list of tools at session start. The description
text in that list is part of what the model reads, which makes it an instruction
channel, which makes it an attack surface.

`postmark-mcp` shipped roughly fifteen clean releases with an identical config
file, then changed what `tools/list` returned.

**Package pins and config-file hashes both miss this**, because nothing on disk
changed. The payload lives in what the server said, not in what the operator
installed.

Agentmetry therefore keeps two independent digests:

| Digest | Covers | Moves when |
|---|---|---|
| `mcp_config_digest` | the configured command line | somebody edits the config |
| `mcp_schema_digest` | the `tools/list` the model was handed | the server changes what it advertises |

**Schema digest moved while config digest held still** is the rug-pull
signature. It needs no model to evaluate and no new detection rule to express.

Several things make the signal survive contact with reality:

- **Pagination is drained before hashing**, and tools are sorted by name, so a
  server splitting 40 tools across three pages instead of two produces an
  identical digest.
- **A failed page discards the accumulated pages**, because a retry appending
  onto a stale prefix would hash to a listing no server ever served.
- **A failed listing emits an explicit `unavailable` event** rather than
  vanishing. Silence is not the same as unknown.
- **Growing out of an empty baseline is a first sighting, not a change.** A
  registry that intermittently lists empty, or a server listed before it
  finished starting, would otherwise write an empty baseline and turn the next
  healthy listing into a rug-pull alert. Deliberately one-way: going from
  populated to empty is still a change, because tools disappearing is real.
- **The `initialize` handshake is recorded.** `serverInfo.version` separates
  "they shipped a release" from "the digest moved and the version did not",
  which is the shape worth investigating first. That version is
  attacker-controlled, so it discriminates benign churn and is explicitly not a
  security boundary.
- **Each tool carries its own digest**, so an alert names the tool that moved
  rather than only the server. Storing the listing itself would answer the same
  question and would mean writing a poisoned description into the trail and
  forwarding it to a SIEM, so the answer is a hash per tool instead: enough to
  point at one tool, never enough to carry the payload.

The last four exist because six strangers reviewed the design in public and
found them. That is the intended failure mode of publishing a heuristic.

---

## 7. Coverage attestation

A hook lives in a file the developer owns. `.cursor/hooks.json` can be deleted.
`claude --no-hooks` skips it. The orchestrator can be stopped. No user-space
recorder prevents any of that, and the honest answer to "what stops my developer
removing this" is that **removal changes what the recorder says about itself**.

"Alert when a machine stops sending events" does not work, because idle and
disabled both emit nothing, and silence is not evidence.

So the recorder attests on an interval whether or not anybody is coding, and
reports per agent surface in **four states rather than a boolean**:

`covered` · `uncovered` · `absent` · `unknown`

"The hook was removed" and "this agent was never installed here" deserve
opposite responses. A fleet that learns the tamper signal is always on has no
tamper signal left.

---

## 8. Where the evidence goes

Agentmetry is a sensor, not a console. The customer's SIEM stays the console.

Forwarders ship for **Splunk HEC**, **Elastic ECS**, **Google SecOps UDM**,
**CloudEvents**, and Loki via Alloy. All fourteen published detections are also
exported as **Sigma rules**, generated from the engine by replaying the
benchmark corpus and reading the `Detection` objects it emits, so a severity
that changes in the rules changes in the Sigma pack on the next run and a test
fails if nobody re-runs the generator.

Generating rather than hand-writing caught a real defect on the first run:
`encoded-command-download` deliberately emits two severities, critical for
remote code fetched and executed and low for local content piped into an
interpreter. A hand-written pack would have carried one level and routed half
the firings to the wrong queue.

---

## 9. How the claims are kept honest

This is a security tool, so the interesting question is not what it detects but
why you should believe the numbers.

**A benchmark anyone can run in about ten seconds.** 57 recorded sessions, 26
attack and 31 benign. Current result: 26 of 26 expected detections fire, 0
missed, 0 false positives. **13 of the 14 published rules have corpus
coverage**, and the one that does not is named in the generator with a reason
rather than rounded up.

That "0 false positives" is worth one more sentence, because in the previous
release it was true and hollow. Four false positives were known, filed and
shipping, and the corpus did not contain them, so the number measured a set
chosen to exclude the failures. As of 0.7.0 all four are in the corpus as
tagged benign cases and a regression fails CI.

```bash
agentmetry benchmark
```

**A ruleset fingerprint.** The four Python files that define detection, plus the
YAML manifest, are hashed together. During an evaluation period they are frozen,
and the fingerprint is published, so "four clean weeks" cannot quietly mean four
different rulesets.

The freeze is a commitment, not a hiding place. It was broken deliberately at
0.7.0 to fix the four false positives above, which moved the fingerprint and
restarted the clock at three of four weeks. A clean gate measured against a
ruleset that fires critical on `.env.example` is not worth the weeks it takes.

**A rule that cannot fire is not published.** `autonomous-unapproved-write` keys
on an actor type that the bus and SDK paths produce and no IDE capture surface
does: across roughly 32,000 events of real traffic from five agent surfaces the
actor is `human`, `agent` or `system` and never once `autonomous`. It was
counted in the rule total and exported to Sigma at severity high. It is now
registered but experimental, uncounted and unexported, until a capture surface
produces the signal it reads.

**Tests that pin documentation to reality.** The README quotes a benchmark
result and invites the reader to reproduce it. A test asserts the quoted numbers
match the corpus, because the README once advertised 17 cases while the corpus
held 20 and the landing page advertised 9 rules while the engine shipped 15.
Numbers rot; a failing test is cheaper than being corrected by your first
serious reader.

The same guard now covers the wire. `ExternalIngestBody` silently dropped every
field it did not declare, so a feature could pass its unit tests and vanish at
the HTTP boundary. That shipped twice, once for command traits and once for the
MCP per-tool digests. A round-trip test builds payloads with the real capture
builders and fails if any key does not survive.

**1148 tests, 81% line coverage**, enforced by a floor in CI, on Linux and
Windows.

---

## 10. What it does not do

Stated so nobody has to discover it during an incident.

- **It does not see agents it is not installed on.** Unmanaged ChatGPT,
  Copilot, or a colleague's laptop are invisible. That is a CASB problem and
  other products solve it.
- **It records and detects; it does not block by default.** Blocking exists, is
  opt-in, at the hook boundary, and stays the smaller half of the product.
- **It is not a sandbox and not an agent runtime.** It does not execute agents
  and does not isolate them.
- **A quiet MCP fingerprint is not proof of a stable server.** A server can hold
  its listing identical and change what a tool does at call time. The listing
  digest is a tripwire, not a guarantee.
- **It does not spawn MCP servers to poll them.** Running `npx -y` on a schedule
  would fetch and execute whatever the registry currently serves, which is the
  attack, performed by the recorder.
- **It does not store prompts, completions, descriptions, or command text.**

---

## 11. Reproducing everything above

```bash
pip install agentmetry
agentmetry doctor                  # install health
agentmetry benchmark               # 50 cases, expect 0 missed / 0 false positives
agentmetry verify --trail data/agentmetry-trail.jsonl
agentmetry stats --days 7
```

Source: <https://github.com/blitzcrieg1/agentmetry>. Apache-2.0.

Detection rules, their provenance, and the research they were built against are
documented in [detection-rules.md](detection-rules.md). The event schema is in
[agentmetry-event-schema.md](agentmetry-event-schema.md). Anchoring is in
[anchoring.md](anchoring.md).

Being told a detection is wrong is worth more than being told it is right. If a
rule fires on something legitimate on your machine, that is the highest-value
issue you can open.
