# Enterprise lane (optional, not the beta product)

Agentmetry beta is a **local-first sensor for AI coding agents**: hooks, a JSONL trail,
sequence detections, and forwarders into a SIEM the customer already runs. It is
not a console. A hosted fleet console is allowed for Agentmetry Enterprise and
is not built. The open-source sensor does not need it. This document names what
**enterprise production** would add without pretending it ships today.

## What beta ships (Buyer A)

| Capability | Status |
|------------|--------|
| IDE + MCP cooperative capture | Shipped (Tier B) |
| Sequence detections + DLP + tool policy at hook boundary | Shipped |
| Local dashboard + JSONL hash chain | Shipped |
| Forward to Splunk, Elastic, Google SecOps, webhook, CloudEvents. Loki via Alloy. Microsoft Sentinel is implemented and not yet run against a live workspace | Shipped |
| YAML detection thresholds + count rules | Shipped (`agentmetry/policies/detection/manifest.yaml`) |
| Sigma export pack | Shipped |

## Honest limits (say these in sales docs)

1. **Hooks are cooperative.** A determined agent can bypass hooks and use raw syscalls. Mitigation: optional host telemetry (below), not denial.
2. **Local JSONL is tamper-evident, not non-repudiation.** Root on the host can delete files. Mitigation: forward to customer SIEM; optional Rekor/TPM sinks (roadmap).
3. **Default privacy hashes commands.** Sequence rules use hook-side `tool.traits` labels so detections work without storing plaintext (see `core/audit/detection/traits.py`).

## Enterprise lane (Buyer B — only with paying design partner)

| Item | When | Notes |
|------|------|-------|
| Single-binary packaging (PyInstaller/Nuitka) | Next hardening sprint | Fleet install without venv |
| mTLS on SIEM forwarders | Next hardening sprint | Customer infra, not vendor cloud |
| Rekor / transparency-log sink | Optional sink | Append-only evidence without Agentmetry cloud |
| Sigma **import** for point alerts | After YAML count rules | Sequence rules stay YAML/Python |
| Linux eBPF sidecar (Tetragon/tracee) | Design partner request | Tier-D host truth; **complement**, not replace hooks |
| Rust/Go rewrite | ≥500-seat paid fleet | Not before revenue |

## What we will not build

- A hosted dependency in the open-source sensor
- Killing the local dashboard (operator persona needs it)
- Email autopilot / LangGraph skill runtime (removed from repo scope)

Revised 2026-10-02: this list used to rule out a vendor multi-tenant control
plane and an Agentmetry-hosted backend. Both are now allowed for Enterprise, and
neither is built. The open-source sensor stays local-first. See
[open-core split](../commercial/open-core-split.md#hosted-enterprise-is-allowed).

See [ROADMAP.md](../../ROADMAP.md) and [COMMERCIAL.md](../../COMMERCIAL.md).
