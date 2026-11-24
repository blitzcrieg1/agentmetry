# FAQ

Answers to questions that came up in the wild (HF Show and Tell topic 191787,
r/netsec, r/dfir). If your question is not here, ask in
[GitHub Discussions](https://github.com/blitzcrieg1/agentmetry/discussions).

## Detection rules

**Does the staging rule fire for other spellings of a host, like a dotted IP or a trailing dot?**
Yes for fetch-then-run of the same file, regardless of host spelling. The
staging-host regex is hostname based, so an IP literal does not match it, but the
rule's second branch is host agnostic: if the fetched basename is the executed
basename, it fires critical. Trailing-dot (`huggingface.co.`), uppercase and
subdomain forms all match the hostname regex directly. These cases are pinned in
the benchmark corpus (`attack_hf_trailing_dot_stage_execute`,
`attack_ip_literal_stage_execute`, `benign_hf_readme_fetch_then_python_c`), so CI
enforces the behavior on every run.

**Does the trail hash-check a fetched file against what actually ran?**
No, and that is a deliberate boundary. The hook layer records what the agent
*reported*; it cannot vouch for bytes on disk. Integrity of the artifact belongs
below the hook: pair Agentmetry with a kernel-layer sensor (the Enterprise Sysmon
collector signs and minimizes kernel-observed events; on Linux, ingest
Tetragon/AgentSight over OTLP). The trail itself is hash-chained and can be
anchored off-host (see `agentmetry-anchors`), which catches tampering with the
log, not with the file.

**What about a detached background process that fetches and runs a second file?**
Known gap at the hook layer: the trail holds the spawning command, not the
child's later actions. The kernel sensor layer (Sysmon/ETW on Windows, eBPF
sources on Linux) is what closes this. Until your deployment has one, treat
hook-only coverage as "agent-reported activity", not full endpoint visibility.

**The token-then-cloud-CLI rule fires on order alone?**
Partly, and it is tracked as [#431](https://github.com/blitzcrieg1/agentmetry/issues/431):
`source .env` style loads do not start the sequence, and a token sent only to its
own issuer's CLI/hosts earns no credential half. The fix direction is linking the
secret to where it actually goes (argv, URL, foreign host), not just the order.

## Coverage boundaries

**Is absence of an event evidence that nothing happened?**
No. Hooks are cooperative: an agent whose hooks are removed or bypassed leaves no
event (the heartbeat flags removed hooks, not skipped sessions). This is why the
README says "pair it with EDR", and why the kernel collector exists. The trail
labels each event with its capture source so an auditor can tell hook-reported
from kernel-observed.

## Privacy

**What exactly gets stored?**
The minimum needed for detection: tool name, outcome, hashes of inputs, timestamps,
host and session identifiers, and minimized event fields from kernel sources (no
full paths, command lines or user names; file targets are stored as SHA-256). The
Merkle anchors published to the anchors repo disclose only event counts and
checkpoint times, never content.

**Where does the data go?**
Nowhere by default. Local-first: the trail stays on your machine unless you
configure a forwarder to your own SIEM (Sentinel, Splunk, Elastic, Loki, OTLP).
