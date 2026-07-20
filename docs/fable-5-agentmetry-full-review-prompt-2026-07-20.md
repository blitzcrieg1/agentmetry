# Fable 5 — Agentmetry full project review prompt (2026-07-20)

Copy everything below the line into **Fable 5** (or Claude Opus with full repo + web access).

**Context:** Agentmetry is a **local-first mini-SIEM for AI coding agents** (public alpha → beta). The repo was trimmed on 2026-07-20 to remove legacy **agentic-os / Blackbox / email autopilot / LangGraph** residue — product scope is **SIEM only**: hooks → canonical JSONL → detection → dashboard → SIEM sinks.

**Your job:** One brutally honest report (~4,000–8,000 words). Verify every README/marketing claim against code. No cheerleading. Prioritize what blocks beta vs what is nice-to-have.

**Do not implement fixes in this pass** — review, research, prioritize. Cite `path:line` evidence.

---

## PROMPT START

### 0. Scope guardrails

Agentmetry **is:**
- Tier B IDE lifecycle hooks (Cursor, Claude, Codex, Antigravity, Qwen, Kimi, Qoder, CodeBuddy)
- MCP stdio audit proxy
- Canonical schema v1.1.0, MITRE tagging, sequence detections, DLP, tool policy
- JSONL hash chain, SQLite trail index, live detection checkpoint
- Phase 1 dashboard (flight recorder, detections, analytics)
- SIEM forwarding (file, webhook, Elastic, Splunk, Loki, Sigma, alert webhook)

Agentmetry **is not** (removed or out of scope — flag any residue you find):
- Email autopilot, Gmail send, `customer_reply`, Telegram
- LangGraph skill runtime, Obsidian plugin, vault-defined skills
- Cloud SaaS, multi-tenant ledger

If you find docs/code still implying the old dual product, list it as **P0 confusion debt**.

---

### 1. Inspect these surfaces first

| Area | Path |
|------|------|
| Hook ingest + enforce | `scripts/agentmetry_ingest.py` |
| Ingest API + live detection | `apps/orchestrator/core/audit/ingest.py`, `detection/live.py` |
| Rules registry | `apps/orchestrator/core/audit/detection/rules.py` |
| DLP / tool policy | `policies/dlp/manifest.yaml`, `policies/tool/manifest.yaml` |
| Hash chain | `core/audit/trail_chain.py`, `sinks.py` |
| External canonical | `core/audit/external.py` |
| Dashboard shell | `apps/dashboard/components/mission-control.tsx` |
| Chinese agents | `docs/integrations/chinese-agents.md`, `hook_bootstrap.py` |
| HF forensics playbook | `docs/compliance/local-llm-forensics.md` |
| Roadmap truth | `ROADMAP.md`, `README.md`, `CHANGELOG.md` [Unreleased] |
| Config (should be SIEM-only) | `apps/orchestrator/core/config.py`, `.env.example` |
| CLI | `apps/orchestrator/cli/__init__.py` |
| Tests | `apps/orchestrator/tests/` (~260+ pytest) |

---

### 2. Changes shipped 2026-07-20 (verify, don’t trust CHANGELOG)

**PR #23 merged to `master`** — four feature commits:

#### A. HF July 2026 incident patterns
- **Rules:** `credential-read-then-cloud-api`, `dotfile-read-then-git-push`, `remote-staging-then-execute`
- **DLP:** `huggingface_token` (`hf_…`)
- **MITRE:** `.docker/config.json`, `.config/gcloud` → T1552 upgrade paths
- **Demo:** `python scripts/demo.py --scenario hf|classic|all`
- **Docs:** `docs/compliance/local-llm-forensics.md` (asymmetry problem — commercial APIs refuse incident payloads)
- **Tests:** `test_detection_hf_incident.py` (14 tests)

#### B. Chinese agent capture — Sprint A
- Qwen Code + Kimi Code hook adapters (Claude-family JSON stdin protocol)
- `install_qwen_hooks.ps1`, `install_kimi_hooks.ps1`
- First-class `source_app`: `qwen`, `kimi`, `crewai`, `opensre`
- Dashboard badges, ingest API enum
- **Tests:** `test_chinese_agent_hooks.py`

#### C. Chinese agent capture — Sprint B
- Qoder + CodeBuddy hooks + install scripts
- `SubagentStart` / `SubagentStop` capture
- **Rule:** `subagent-swarm-burst` (≥5 subagents/session, severity high)
- CN cloud CLI in credential-read rule: `aliyun`, `tencentcloud`, `ossutil`, `coscmd`, `bce`
- **DLP:** Tencent `AKID…`, Chinese provider `*_API_KEY=` assignments, extended `agent_env_override`
- **Tool policy:** kimi/qwen/deepseek weaponization; block writes to `.qwen/`, `.qoder/`, `.codebuddy/`, `.kimi-code/`
- **Tests:** `test_chinese_agent_sprint_b.py`

#### D. Chinese agent capture — Sprint C
- Kimi **stream-json** print-mode ingest: `kimi -p "…" --output-format stream-json | python scripts/agentmetry_ingest.py kimi stream-json`
- **Rules:** `session-tool-burst` (≥40 tools/session), `host-subagent-swarm-burst` (≥8 across sessions on `host_id`)
- **Host aggregation:** `live_store.py` host-level window + `observe_host()` in `live.py`
- **DLP:** `dashscope_api_token` (bare `sk-` + 32 hex)
- **Trae stub:** `adapters/trae/README.md` — MCP proxy only until ByteDance ships hooks
- **Script:** `install_chinese_hooks.ps1` (all four CLIs)
- **Tests:** `test_chinese_agent_sprint_c.py`

#### E. Repo cleanup (same day, may be uncommitted when you read)
- Removed: `docs/advanced-governed-runtime.md`, old Fable/Claude operator prompts, email-framed compliance checklist
- Trimmed: `config.py`, `.env.example`, CLI `status` (no dead `/skills/*` API), README (no LangGraph section)
- Moved: root `tests/test_dlp_scanner.py` → `apps/orchestrator/tests/`

**Deliverable:** Table — each item above: **Verified ✓ / Oversold / Broken / Untested**.

---

### 3. Changes proposed but NOT shipped (evaluate priority)

| Item | Source | Your recommendation |
|------|--------|---------------------|
| Tag **v0.2.1** with [Unreleased] CHANGELOG | Operator | Ship now / wait |
| Phase 1 rules: consecutive writes outside project root | ROADMAP P1 | Implement / defer |
| Rapid-fire denials rule | ROADMAP P1 | Implement / defer |
| Package-install tampering rule | ROADMAP P1 | Implement / defer |
| YAML custom rules loader | ROADMAP Phase 2 | Architecture review first |
| Detection benchmark fixtures in CI | ROADMAP Phase 2 | High leverage? |
| OTLP export | ROADMAP Phase 2 | vs Elastic/Splunk depth |
| Marketing site: distinct detection screenshot | ROADMAP P1 | GTM blocker? |
| Trae full hook adapter | When ByteDance ships | Watch issue #397 |
| Kimi incremental stream-json deltas | kimi-cli #2179 | Worth adapter work? |
| Cross-host swarm (needs fleet ingest) | Sprint C note | Out of scope honest? |
| Dashboard dead code: LangGraph WS handlers in `store.ts` | Cleanup debt | Delete list |

---

### 4. Part A — Full project review

#### 4.1 Code & architecture
Trace: IDE hook → `agentmetry_ingest.py` → DLP/tool policy → POST ingest → canonical → SQLite + JSONL → live detection → sinks.

Report:
1. **Bugs** — races, silent loss, auth bypass, TOCTOU, hash-chain gaps, detection re-fire after restart, Windows failures
2. **Security model honesty** — pre-execution vs post-fact; evasion paths (MCP bypass, subagent, rename, direct HTTP)
3. **Architecture debt** — what still references removed governed runtime; what to delete next
4. **Test gaps** — top 5 untested critical paths

Output: findings table with **Severity**, **Evidence**, **Fix complexity** (hours/days/weeks).

#### 4.2 Concept & positioning
- Is “local-first mini-SIEM for AI coding agents” credible vs AgentLens, mcp-audit, mcp-tap, Cursor native audit?
- Wedge: multi-IDE + sequence detections + hook-boundary block — still defensible in July 2026?
- Persona fit: solo Windows dev vs security engineer vs EU deployer

#### 4.3 Progress vs beta gates (ROADMAP)
1. 4 green dogfood weeks
2. `agentmetry doctor` green on 3× Windows 11
3. `verify --trail` in README demo
4. agentmetry.ai matches local dashboard

Score each 0–100% with evidence.

#### 4.4 Dashboard & UX
- Flight recorder, detections triage, analytics — world-class or demo-grade?
- Source badges for 10+ apps — scalable?
- False positive operator workflow — good enough?

---

### 5. Part B — Deep research (web + papers)

Search and synthesize **July 2025 – July 2026** sources. For each, answer: **What should Agentmetry implement?** (rule, DLP pattern, doc, or explicit out-of-scope)

#### 5.1 Incidents & disclosures
- [Hugging Face July 2026 security incident](https://github.com/huggingface/blog/blob/main/security-incident-july-2026.md) — agentic intrusion via coding agents; asymmetry with commercial LLM forensics
- Nx **s1ngularity** campaign (2025) — already partially covered (`s1ngularity_exfil_ioc`, double base64 DLP)
- Any similar **agent credential theft** disclosures in 2026

#### 5.2 Academic / industry research
- [Agent Data Injection (arXiv:2607.05120)](https://arxiv.org/abs/2607.05120) — ADI chains; map to existing rules
- [MCPTox (AAAI)](https://ojs.aaai.org/index.php/AAAI/article/view/40895) — tool poisoning on real MCP servers
- [MCP-TDP benchmark (arXiv:2605.24069)](https://arxiv.org/html/2605.24069v1) — tool description poisoning
- [MCP security empirical study (arXiv:2506.13538)](https://arxiv.org/html/2506.13538v5)
- [mcp-sec-audit (arXiv:2603.21641)](https://arxiv.org/html/2603.21641v1) — pre-deployment MCP capability audit
- [Agent Audit (arXiv:2603.22853)](https://arxiv.org/html/2603.22853v1) — static analysis for agent apps
- OWASP **Agentic Top 10** (2025/2026) — gap analysis vs current rules/DLP

#### 5.3 Chinese AI agent ecosystem
- Qwen Code, Kimi Code, Qoder, CodeBuddy, Trae, DeepSeek CLI — hook maturity, swarm patterns
- CN cloud CLIs (Aliyun, Tencent, Baidu) — coverage gaps in rules/DLP
- DashScope / Moonshot / Zhipu token formats — false positive risk

#### 5.4 Competitive / adjacent tools
- Cursor hook partner program, Codex JSONL, Claude Code hooks parity
- Datadog LLM observability vs local SIEM wedge
- Sigma/YARA community rules for agent abuse

**Deliverable:** Prioritized **implementation backlog** (max 20 items):

| Priority | Item | Type (rule/DLP/hook/doc/out-of-scope) | Effort | Impact | Source citation |
|----------|------|---------------------------------------|--------|--------|-----------------|

Mark each **Solo-dev realistic?** (Y/N)

---

### 6. Part C — Strategic verdict

Answer plainly:

1. **Go / pivot / kill** for public beta in Q3 2026?
2. **Top 3 wins** if you had one week
3. **Top 3 risks** that could embarrass the project on HN/GitHub
4. **One thing to delete** (not document better)
5. **One thing to double down on**

---

### 7. Output format

```markdown
# Agentmetry full review — [date]
## Executive verdict (≤200 words)
## Legacy residue audit (post-cleanup)
## Shipped 2026-07-20 verification table
## Code/architecture findings
## Research-backed backlog
## Beta gate scorecard
## Strategic recommendations
## Appendix: sources consulted (URLs)
```

---

## PROMPT END

**Attachments for Fable:** `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `docs/integrations/chinese-agents.md`, `docs/compliance/local-llm-forensics.md`, `policies/dlp/manifest.yaml`, `apps/orchestrator/core/audit/detection/rules.py`

**Optional:** Run locally before review:
```powershell
cd apps/orchestrator && pytest -q && ruff check core api tests
python scripts/demo.py --scenario all
scripts\agentmetry.bat doctor
```
