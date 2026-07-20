# Open-core split: Apache 2.0 vs. Enterprise (ELv2)

Agentmetry uses a **two-repo open-core model**. The public repository stays
Apache 2.0 forever for the developer utility layer. Commercial add-ons ship as a
separate proprietary package (`agentmetry-enterprise`) that hooks into the
orchestrator via standard Python entry points.

This document is the Project Owner's **licensing intent**, not a contract.
See [COMMERCIAL.md](../../COMMERCIAL.md) and [CLA.md](../../CLA.md).

## Integration mechanic

Enterprise features are optional. The orchestrator loads extensions from the
setuptools group `agentmetry.extensions` at startup (`core/extensions.py`).
When the enterprise wheel is not installed, behavior is identical to OSS.

```toml
# agentmetry-enterprise/pyproject.toml
[project.entry-points."agentmetry.extensions"]
enterprise = "agentmetry_enterprise.register:register"
```

## Apache 2.0 forever (public `agentmetry`)

| Area | What ships |
|------|------------|
| **Capture** | IDE hooks (Cursor, Claude Code, Codex, Antigravity), MCP audit proxy, external ingest adapters |
| **Schema** | Canonical event format v1.1.0, MITRE ATT&CK per-tool tagging |
| **Detection core** | Sequence-rule executor, live detection engine, community rule pack |
| **Native YAML rules** | `policies/detection/manifest.yaml` spec — thresholds, session count rules, hot-reload |
| **DLP & tool policy** | Regex DLP manifest, tool allow/deny YAML, hook-boundary enforcement |
| **Storage** | SQLite index, JSONL hash chain, evidence export |
| **Forwarders** | File, webhook, Splunk HEC, Elastic ECS, Loki — API key / token auth over HTTPS |
| **Sigma export** | SIEM pack for forwarding Agentmetry events to existing Sigma pipelines |
| **Dashboard** | Local Flight Recorder UI (single-operator hunt layout) |
| **CLI** | `start`, `stop`, `status`, `doctor`, `stats`, `export`, `verify` |

## Enterprise / ELv2 (private `agentmetry-enterprise`)

| Area | What ships | First SKU |
|------|------------|-----------|
| **Certified fleet installers** | Single binary (Nuitka/PyInstaller), `.msi`, `.pkg`, brew tap | SKU 1 |
| **Enterprise support & SLA** | Priority support, Splunk/Elastic onboarding | SKU 1 |
| **Sigma dialect import** | Parser: standard Sigma YAML → Agentmetry rules (not native YAML) | SKU 2 |
| **Scoped auth** | `ingest` / `read` / `admin` tokens, rate limiting | SKU 1–2 |
| **mTLS forwarders** | Client cert auth to customer Splunk/Elastic/Loki | SKU 1–2 |
| **Compliance packs** | Evidence templates for SOC 2, ISO 27001, EU AI Act | SKU 2 |
| **Premium sinks** | Rekor/Trillian transparency log, optional TPM local signing | SKU 2 |
| **Customer-owned rule distribution** | Pull rules from a repo or bucket **the customer controls** | SKU 2 |
| **Advanced DLP** | Shannon entropy detectors, YARA payload scanning | SKU 2 |
| **eBPF sidecar adapter** | Tetragon/tracee → canonical schema as optional Tier-D | Design partner |

## Critical boundary: native YAML vs. Sigma import

**Native Agentmetry YAML** (detection manifest, DLP manifest, tool policy) stays
open source. Analysts can ship detections in YAML without a commercial license.

**Sigma dialect import** (porting an existing library of Sigma rules) is
enterprise. That is the "500 rules without Python PRs" unlock for SOC teams who
already standardize on Sigma syntax.

## What we will not build (either repo)

- Vendor multi-tenant cloud control plane
- Agentmetry-hosted SIEM replacing customer Splunk/Elastic
- Replacing IDE hooks with eBPF as the primary capture layer
- Full Rust/Go rewrite before paid fleet demand (≥500 seats)

See [enterprise-lane.md](../compliance/enterprise-lane.md) for honest beta limits
and optional enterprise path.

## Trademark

"Agentmetry Enterprise" is a commercial offering name. The OSS project remains
"Agentmetry". See [TRADEMARK.md](../../TRADEMARK.md).

## Contact

Commercial inquiries: **legal@agentmetry.ai**
