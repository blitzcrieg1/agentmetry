# Enterprise lane (optional, not the beta product)

Agentmetry beta is a **local-first SIEM for AI coding agents** — hooks, JSONL trail,
sequence detections, customer-owned SIEM forwarders. This document names what
**enterprise production** would add without pretending it ships today.

## What beta ships (Buyer A)

| Capability | Status |
|------------|--------|
| IDE + MCP cooperative capture | Shipped (Tier B) |
| Sequence detections + DLP + tool policy at hook boundary | Shipped |
| Local dashboard + JSONL hash chain | Shipped |
| Forward to Splunk / Elastic / Loki / webhook | Shipped |
| YAML detection thresholds + count rules | Shipped (`policies/detection/manifest.yaml`) |
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

## What we will not build (12-week commitment)

- Vendor multi-tenant cloud control plane
- Replacing customer SIEM with Agentmetry-hosted ClickHouse
- Killing the local dashboard (operator persona needs it)
- Email autopilot / LangGraph skill runtime (removed from repo scope)

See [ROADMAP.md](../../ROADMAP.md) and [COMMERCIAL.md](../../COMMERCIAL.md).
