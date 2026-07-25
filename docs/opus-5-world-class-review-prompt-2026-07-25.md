# Opus 5 — Agentmetry world-class review prompt (2026-07-25)

Copy everything below the line into **Claude Opus 5** (or Cursor Agent with Opus 5, full repo access, and web search).

**Context:** Agentmetry is a **local-first mini-SIEM for AI coding agents** (public alpha → beta). Two repos:

| Repo | Path / URL | License | Role |
|------|------------|---------|------|
| **Public** | `C:\Users\spiro\Projects\agentic-os` · https://github.com/blitzcrieg1/agentmetry | Apache 2.0 | Core product: hooks → canonical JSONL → detection → triage → dashboard → SIEM |
| **Enterprise** | `C:\Users\spiro\Projects\agentmetry-enterprise` · https://github.com/blitzcrieg1/agentmetry-enterprise (private) | ELv2 intent | Certified MSI build, extension hook, sales kit; most modules are stubs |

**Version:** `0.2.1` (`apps/orchestrator/core/version.py`)

**Your job:** One brutally honest report (~6,000–12,000 words). Verify every README/marketing claim against code in **both** repos. No cheerleading. No fabricated market numbers (ACV, NRR, TAM) — the operator will not use invented revenue metrics in a deck.

**Explicitly out of scope for your recommendations:** “Send 5 pilot outreach emails.” The operator already knows that is the GTM bottleneck. Focus on product, engineering, UX, architecture, and enterprise readiness instead.

**Do not implement fixes in this pass** — review, benchmark, rank, prioritize. Cite `path:line` evidence.

---

## PROMPT START

### 0. Scope guardrails

Agentmetry **is:**
- Tier B IDE lifecycle hooks (Cursor, Claude, Codex, Antigravity, Qwen, Kimi, Qoder, CodeBuddy, Trae stub)
- MCP stdio audit proxy
- Canonical schema v1.1.0, MITRE tagging, correlated sequence detections, DLP, tool policy
- JSONL hash chain, SQLite trail index, live detection checkpoint, **detection triage/disposition loop**
- Phase 1 dashboard (flight recorder, detections triage, analytics)
- SIEM forwarding (file, webhook, Elastic ECS, Splunk HEC, Loki, Sigma pack, alert webhook)
- Open-core extension hook (`core/extensions.py`) + enterprise MSI build scaffolding

Agentmetry **is not** (removed or out of scope — flag any residue):
- Email autopilot, Gmail send, Telegram, LangGraph skill runtime, Obsidian plugin
- Vendor multi-tenant cloud control plane (CrowdStrike-style Falcon cloud)
- “AI Act compliance product” — deployer evidence only, not a QMS
- Rust rewrite, eBPF-as-replacement for hooks

**Strategic model the operator chose (evaluate, don’t relitigate unless wrong):**
- **Sensor + customer SIEM**, not vendor cloud console (`docs/integrations/fleet-via-siem.md`)
- **Triage is trail-backed evidence**, recomputable via `rebuild_from_trail()` — not a vendor data moat
- **Pilot SKU:** $7,500 / 90 days / ≤25 devs — MSI + Splunk HEC help + 4h support
- **Kill gate:** 4 green dogfood weeks before new drivers/features

If docs/code still imply the old “Agentic OS / dual product,” list as **P0 confusion debt**.

---

### 1. Changes shipped 2026-07-25 (verify — do not trust CHANGELOG alone)

Public repo commits today (`git log --since=2026-07-25`):

| Commit | Summary | Verify |
|--------|---------|--------|
| `dc61091` | **fleet_id** — `AGENTMETRY_FLEET_ID` on all canonical events via `core/audit/identity.py`; ECS maps to `organization.id`; Sigma rule for `risk_accepted`; `rebuild_from_trail()` wired in `api/main.py` lifespan | ✓/✗ |
| `c60a9b9` | Untrack local launch config; evidence pack schema version fix | ✓/✗ |
| `ce1acf4` | Docs: triage loop + `fleet-via-siem.md` | ✓/✗ |
| `9397874` | Changelog backfill since v0.2.1 | ✓/✗ |
| `e71a09a` | CI: Windows + Ubuntu matrix; dashboard vitest (79 tests) | ✓/✗ |
| `39c4ae5` | **Detection triage** — `detection_disposition` events, SQLite materialized view, API routes, dashboard triage UI, evidence pack schema 2.1 | ✓/✗ |
| `d800c66` | Test isolation — `conftest.py` redirects store paths; no longer writes to dev trail | ✓/✗ |
| `18ca407` | Version single source `0.2.1` in `core/version.py` | ✓/✗ |

**Deliverable:** Table — each item: **Verified ✓ / Oversold / Broken / Untested** with evidence.

Also verify these **known gaps** the prior session identified (may or may not be fixed):

| Gap | Status to confirm |
|-----|-------------------|
| Stale nested clone at `agentic-os/agentmetry/` (~11MB, own `.git`) | Still present? Safe to delete? |
| Sigma pack has disposition rule but no rule for untriaged detections | |
| `adapters/ecs.py` — other action types still fall through to generic `"process"`? | |
| Enterprise `fleet/` — only `__init__.py` docstring; **no** `ota_client.py` | Do not cite files that don't exist |
| MSI built locally (~53.7 MB, unsigned); clean-room VM not run | |
| `fleet_id` empty string when unset — SIEM query ergonomics | |

---

### 2. Inspect these surfaces first

#### Public repo (`agentic-os`)

| Area | Path |
|------|------|
| Hook ingest + enforce | `scripts/agentmetry_ingest.py` |
| Ingest API + live detection | `apps/orchestrator/core/audit/ingest.py`, `detection/live.py` |
| Triage / disposition | `core/audit/detection/disposition.py`, `api/routes/` (disposition endpoints) |
| Fleet identity | `core/audit/identity.py`, `core/config.py` |
| Rules registry | `core/audit/detection/rules.py` |
| DLP / tool policy | `policies/dlp/manifest.yaml`, `policies/tool/manifest.yaml` |
| Hash chain | `core/audit/trail_chain.py`, `sinks.py` |
| External canonical | `core/audit/external.py` |
| ECS / Splunk adapters | `core/audit/adapters/ecs.py`, `splunk.py` |
| Extension hook | `core/extensions.py`, `api/main.py` lifespan |
| Dashboard shell + triage UI | `apps/dashboard/components/mission-control.tsx`, `detections-panel.tsx`, `flight-recorder-panel.tsx` |
| Sigma pack | `docs/integrations/sigma/` (4 rules) |
| Fleet SIEM guide | `docs/integrations/fleet-via-siem.md` |
| Open-core split | `docs/commercial/open-core-split.md`, `COMMERCIAL.md` |
| Roadmap truth | `ROADMAP.md`, `README.md`, `CHANGELOG.md` |
| Tests | `apps/orchestrator/tests/` (**524** pytest), `apps/dashboard/` (**79** vitest) |

#### Enterprise repo (`agentmetry-enterprise`)

| Area | Path |
|------|------|
| Extension entry | `src/agentmetry_enterprise/register.py` |
| Stubs (docstrings only?) | `auth.py`, `sigma_importer/`, `sinks/`, `compliance/`, `fleet/` |
| SKU 1 build | `build/build-msi.ps1`, `pyinstaller_build.py`, `wix/agentmetry.wxs`, `clean-room.md` |
| Packaging tests | `tests/test_packaging.py`, `tests/test_register.py` (**20** pytest total) |
| Sales kit | `sales/outreach-sequence.md`, `sales/pilot-sow-template.md` |
| Deployment guide | `build/deployment-guide.md` |

**Run locally if possible:**
```powershell
cd C:\Users\spiro\Projects\agentic-os\apps\orchestrator
pytest -q
cd ..\dashboard && npm test -- --run
cd C:\Users\spiro\Projects\agentmetry-enterprise
pytest -q
python scripts/demo.py --scenario all   # from public repo
agentmetry doctor
```

---

### 3. Part A — Full project review

#### 3.1 Code & architecture (public)
Trace: IDE hook → `agentmetry_ingest.py` → DLP/tool policy → POST ingest → canonical (+ `fleet_id`) → SQLite + JSONL → live detection → disposition event → sinks.

Report:
1. **Bugs** — races, silent loss, auth bypass, TOCTOU, hash-chain gaps, detection re-fire, disposition replay correctness, Windows failures
2. **Security model honesty** — cooperative hooks; evasion paths (MCP bypass, hooks disabled, browser ChatGPT, subagent, rename)
3. **Architecture debt** — dead code, duplicate trees, extension hook cleanliness
4. **Test gaps** — top 5 untested critical paths

Output: findings table with **Severity**, **Evidence** (`path:line`), **Fix complexity** (hours/days/weeks).

#### 3.2 UI/UX (dashboard)
Review `apps/dashboard/` as a **security analyst tool**, not a generic admin panel.

Evaluate:
- Information hierarchy (detections strip → feed → inspector → triage panel)
- Triage workflow (`false_positive` / `risk_accepted` note requirement)
- Source badges for 10+ agent apps — scalable?
- Light/dark, column manager, export flows
- Empty states, error states, feed status bar
- Mobile/responsive (probably N/A — say so)
- Comparison to: Splunk ES, Elastic Security, Datadog Cloud SIEM hunt UI, Cursor’s native audit UX (if any)

Score **0–10** on: clarity, speed-to-answer, operator trust, polish, accessibility.

#### 3.3 Features & completeness
Map shipped vs README/ROADMAP claims. Pay special attention to:
- Detection triage loop (new — is it actually “evidence-grade”?)
- Fleet queries (`fleet_id`, `host_id`, `operator_id`, `correlation_id`)
- Live detection durability across restart
- Evidence export + compliance digest
- Chinese agent coverage
- HF July 2026 / ADI paper chains

#### 3.4 Enterprise repo honesty
Separate **what ships in MSI today** vs **what is stub/docstring**:

| Module | Real implementation? | Blocks pilot? |
|--------|------------------------|---------------|
| PyInstaller + WiX MSI | | |
| Dashboard bundling (`register.py` patch) | | |
| `auth.py` scoped tokens | | |
| `sigma_importer/` | | |
| `sinks/` Rekor/TPM | | |
| `compliance/` templates | | |
| Code signing (EV) | | |
| Clean-room build on pristine VM | | |

Is SKU 1 **honestly deliverable** to a paying pilot with current artifacts?

---

### 4. Part B — Competitive benchmark & “world class” ranking

Research **July 2025 – July 2026** and compare Agentmetry to adjacent products. Use web search. For each competitor, one paragraph: what they do better, what Agentmetry does better, and whether the gap is closable by a solo/small team.

**Minimum set to score:**

| Category | Examples to research |
|----------|---------------------|
| **Agent audit / hook tools** | Cursor hooks ecosystem, Claude Code audit, Codex JSONL, mcp-audit, mcp-tap, MCP proxy tools |
| **Agent security startups** | Lakera Guard, Protect AI, Zenity (agent governance), Nudge Security (shadow AI) |
| **Endpoint + SIEM incumbents** | CrowdStrike Falcon (analogy only — we are not building their cloud), Microsoft Defender for Endpoint + Copilot telemetry |
| **Observability** | Datadog LLM Observability, LangSmith, Langfuse, OpenTelemetry gen-ai semconv |
| **Detection content** | SigmaHQ, Elastic detection rules, Splunk ESCU — for agent-specific content gap |
| **Local-first / OSS security** | Wazuh, osquery, Fleet (Kolide), Tetragon/eBPF sidecars |

**Deliverable — World Class Scorecard:**

For each dimension, score **Agentmetry today (0–10)** vs **“world class” bar (10)** and **best-in-class reference** (name the product):

| Dimension | Agentmetry | World-class bar | Reference product | Gap (1–2 sentences) |
|-----------|------------|-----------------|-------------------|---------------------|
| Capture breadth (IDEs/agents) | | | | |
| Detection sophistication (sequences) | | | | |
| Triage / case management | | | | |
| SIEM integration depth | | | | |
| Tamper evidence / chain of custody | | | | |
| Hook-boundary prevention (block mode) | | | | |
| Dashboard UX for SOC | | | | |
| Fleet deployability (MSI/packaging) | | | | |
| Documentation & trust | | | | |
| Test/CI maturity | | | | |
| Open-source community readiness | | | | |
| Enterprise packaging & support readiness | | | | |

**Overall ranking sentence:** “Agentmetry is approximately **X% of the way to world-class** for [primary persona: security engineer running local-first agent SIEM], behind [top 2 references] on [top 3 gaps].”

Be honest if the category is **too new for a defined “world class”** — say what “world class” would mean in 2026 for this niche.

---

### 5. Part C — Research-backed backlog (exclude outreach)

Synthesize recent sources. For each: **implement / doc / explicit out-of-scope**.

#### 5.1 Incidents & papers
- Hugging Face July 2026 agentic intrusion
- Agent Data Injection ([arXiv:2607.05120](https://arxiv.org/abs/2607.05120))
- MCPTox, MCP-TDP, MCP security studies
- OWASP Agentic Top 10 (2025/2026)

#### 5.2 Open questions from prior review (still valid?)
- YAML custom rules loader vs Python-only sequence rules
- Detection benchmark fixtures in CI
- OTLP export vs Elastic/Splunk depth
- Trae full hooks when ByteDance ships
- Cross-host correlation (needs fleet ingest — now partially addressed by `fleet_id`?)
- Dashboard dead code cleanup

**Deliverable:** Prioritized backlog (**max 25 items**, **no outreach**):

| Priority | Item | Repo (public/enterprise) | Type | Effort | Impact | Solo-dev realistic? |
|----------|------|--------------------------|------|--------|--------|---------------------|

Group into:
- **P0 — blocks paid pilot or public beta credibility**
- **P1 — next 4 weeks after pilot interest**
- **P2 — enterprise SKU 2 / design partner**
- **Explicitly defer** (with reason)

---

### 6. Part D — Strategic verdict

Answer plainly:

1. **Go / pivot / kill** for public beta in Q3 2026?
2. **Go / wait / kill** for first paid pilot on current MSI?
3. **Top 5 engineering wins** if you had two weeks (excluding outreach)
4. **Top 5 risks** that could embarrass the project on HN, in a pilot, or in a security review
5. **One thing to delete** (code/docs/debt — not “send more emails”)
6. **One thing to double down on** (the defensible wedge)
7. **Is category creation or product polish the actual bottleneck?** (Honest answer)

---

### 7. Output format

```markdown
# Agentmetry world-class review — [date]
## Executive verdict (≤250 words)
## Overall world-class score & ranking
## Shipped 2026-07-25 verification table
## Public repo: code/architecture findings
## Public repo: dashboard UX review
## Enterprise repo: SKU 1 readiness
## Competitive benchmark (scorecard table)
## Research-backed backlog (no outreach)
## Beta + pilot gate scorecard
## Strategic recommendations
## Appendix: sources consulted (URLs)
```

Tone: direct, evidence-based, respectful of the local-first thesis. Push back when README oversells. Do not recommend building a vendor cloud control plane unless you can prove the thesis is wrong.

---

## PROMPT END

**Attachments for Opus:** both repo roots, `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `docs/commercial/open-core-split.md`, `docs/integrations/fleet-via-siem.md`, `docs/integrations/sigma/`, `apps/orchestrator/core/audit/detection/disposition.py`, `apps/dashboard/components/detections-panel.tsx`, `agentmetry-enterprise/build/deployment-guide.md`, `agentmetry-enterprise/sales/pilot-sow-template.md`

**Local paths (Windows):**
- Public: `C:\Users\spiro\Projects\agentic-os`
- Enterprise: `C:\Users\spiro\Projects\agentmetry-enterprise`
