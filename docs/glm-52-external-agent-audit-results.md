# GLM 5.2 — External agent audit capture research results

**Source:** GLM 5.2 deep research (2026-07-12), web search enabled.  
**Prompt:** [`glm-52-external-agent-audit-research-prompt.md`](./glm-52-external-agent-audit-research-prompt.md)  
**Implementation follow-up:** P0 adapters in `scripts/agentaudit_ingest.py`, `.cursor/hooks.json`, `adapters/claude/`, `adapters/antigravity/`.

---

# Deep research — Capturing tool-use audit logs from Cursor, Claude Code, and Google Antigravity (2024–2026)

## A. Search log

1. `Cursor hooks.json postToolUse afterMCPExecution event names 2025 docs`
2. `Cursor IDE hooks stdin JSON shape conversation_id tool_name tool_input`
3. `Claude Code hooks PreToolUse PostToolUse settings.json configuration 2025`
4. `Google Antigravity IDE agent observability audit log 2025`
5. `Cursor hooks official documentation lifecycle events 2025 site:cursor.com`
6. `Cursor conversation history storage sqlite json local logs forensic`
7. `Claude Code hooks SessionStart PostToolUse stdin JSON fields session_id tool_name`
8. `Antigravity google agent tool calls logging observability changelog`
9. `Cursor hooks afterFileEdit stop beforeShellExecution stdin JSON tool_input command`
10. `".cursor/hooks.json" postToolUse OR afterShellExecution OR afterMCPExecution`
11. `Claude Code hooks PreToolUse PostToolUse exit code 2 block tool_input stdin JSON schema`
12. `Antigravity SDK telemetry tracing trigger execution logs export json`
13. `Antigravity hooks.json beforeToolCall afterToolCall event names schema stdin`
14. `Antigravity safety policy confirm_run_command lifecycle hooks tool call observe`
15. `Claude Code hooks official reference SessionStart SessionEnd UserPromptSubmit PreToolUse PostToolUse`
16. `site:reddit.com cursor hooks audit log tool use observability`
17. `Cursor hooks "afterMCPExecution" OR "afterShellExecution" event exists 2025`
18. `Claude Code transcript storage ~/.claude/projects jsonl session log tool calls`
19. `Langfuse self-hosted local tool call tracing chain of custody agent observability`
20. `OWASP MCP Top 10 rug pulls tool poisoning security audit 2025`
21. `Cursor hooks official documentation site:docs.cursor.com beforeShellExecution beforeMCPExecution stdin`
22. `Netskope OR Zscaler OR "Microsoft Purview" Cursor Claude AI coding agent CASB shadow AI detection`
23. `Anthropic Claude Code terms of service hooks proxy logging personal use permitted`
24. `Helicone Lunary AgentOps Arize Phoenix self-hosted local agent tool call tracing`
25. `GDPR PII logging AI agent tool call arguments redaction hashing compliance EU`
26. `Cursor enterprise team admin audit logs admin API governance 2025`
27. `mitmproxy intercept Anthropic Claude API local proxy tool calls`
28. `Antigravity changelog telemetry tracing execution logs observability export`
29. `Cursor hooks stdin JSON preToolUse postToolUse tool_name tool_input conversation_id fields schema`
30. `site:github.com cursor hooks issue windows broken reliability`
31. `site:reddit.com GoogleAntigravityIDE hooks audit logging observability`
32. `Claude Code hooks PreToolUse approval deny ask production audit trail reddit`
33. `Deep Dive into the new Cursor Hooks` (GitButler blog — opened)
34. `Antigravity hooks docs` (antigravity.google/docs/hooks — opened)
35. `Claude Code hooks schemas gist` (gist.github.com/FrancisBourre — opened)
36. `Antigravity SDK hooks README` (github.com/google-antigravity — opened)

---

## B. Executive summary

1. **All three target IDEs now ship first-party lifecycle hooks** — the operator's Tier B vision is feasible without OS-level scraping. As of March 2026, five of six major agent platforms expose user-facing hooks; only Codex CLI does not.
2. **Cursor's official hooks API is real, current, and matches the operator's event names.** `sessionStart`/`sessionEnd`, `preToolUse`/`postToolUse`/`postToolUseFailure`, `beforeShellExecution`/`afterShellExecution`, `beforeMCPExecution`/`afterMCPExecution`, `beforeReadFile`/`afterFileEdit`, `beforeSubmitPrompt`, `stop` are all documented at `cursor.com/docs/hooks`. The operator's adapter is on the right track — but it is missing the gating (`before*`) events that carry the allow/deny/ask decision.
3. **Claude Code has the cleanest, best-documented hook contract of the three.** Eight events (`PreToolUse`, `PostToolUse`, `Notification`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `PreCompact`, `SessionStart`), stdin envelope with `session_id`/`transcript_path`/`cwd`/`tool_name`/`tool_input`, exit-code-2 blocking, and `permissionDecision: allow|deny|ask`. This maps almost 1:1 to the operator's schema — the operator's "speculative, no confirmed hook API" framing is outdated.
4. **Antigravity is NOT a dead end — it has the most rigorous hook architecture.** Inspect (async, non-blocking, e.g. `PostToolCallHook`), Decide (blocking allow/deny, e.g. `PreToolCallDecideHook`), and Transform (modifying) hooks with TOCTOU-safe ordering, plus a declarative safety-policy engine (`confirm_run_command()`, `policy.deny()`). Events: `PreToolUse`/`PostToolUse`/`PreInvocation`/`PostInvocation`/`Stop`. The operator should promote Antigravity from "speculative" to "P1."
5. **The MCP-proxy adapter is the highest-leverage shared path.** All three clients support MCP, and Cursor's `beforeMCPExecution` + Antigravity's MCP support + Claude Code's `mcp__<server>__<tool>` matchers mean one hardened stdio proxy captures tool calls across all three for MCP-sourced tools.
6. **Cursor's gating hooks return allow/deny/ask** — "ask" is the human-approval-request event the operator's schema needs. `beforeMCPExecution` receives `server`, `tool_name`, `tool_input`, and the MCP config (URL/command).
7. **Antigravity exposes HITL natively** via `ask_permission` and `ask_question` tools, plus `list_permissions`, on top of the policy engine. Approval events are capturable.
8. **Local transcript scrape is a strong fallback/supplement.** Claude Code writes JSONL at `~/.claude/projects/<encoded-path>/<session-id>.jsonl` (full tool-call chain of custody); Cursor stores chats in SQLite `state.vscdb` under `%APPDATA%\Cursor\User`; Antigravity writes `transcript.jsonl` at `<app_data_dir>/brain/<conversationId>/.system_generated/logs/`.
9. **Cursor hooks are fragile on Windows** — three documented failure modes: UTF-8 stdin corruption of non-ASCII chars, `SessionStart` failing when PATH resolves `bash` to the WSL launcher, and a 2.1.6 regression where hook output isn't surfaced to the agent. The operator (Windows) must harden against all three.
10. **Network-layer MITM is viable but captures LLM API traffic, not local tool execution.** LocalAI's MITM proxy and `llm-interceptor` intercept `api.anthropic.com`/`api.openai.com`, redact PII, and reconstruct `tool_use` blocks from the stream — a useful Tier B supplement and the only path for un-instrumentable clients.
11. **Enterprise audit logs exist but are governance-level, not per-tool-call.** Cursor Admin API (Enterprise plan only) emits logins, role/MCP-config/hook changes, spend limits — not individual tool invocations. Microsoft Purview added a Claude Enterprise/Console/API connector in May 2026. CASB/DLP cannot see tool args, identity, or MCP servers — only DNS/TLS metadata.
12. **The operator's hash+redact design is GDPR-aligned.** Art. 25 (data protection by design) and Art. 22 (automated decisions require HITL) favor exactly the SHA-256-of-redacted-args pattern; plaintext tool args in logs are the risk vector.
13. **ToS risk is low for local personal hooking, high for credential relaying.** Anthropic prohibits routing Free/Pro/Max subscription credentials through third parties; local hooks on your own machine for your own audit are permitted. API-key proxying is unambiguously fine.
14. **Competitors instrument your SDK, not external IDE agents.** Langfuse (self-host, MIT), Arize Phoenix (open-source, local), Helicone all require in-process instrumentation — none capture Cursor/Claude Code/Antigravity tool calls out of the box. That is precisely the white-space AgentAudit Tier B occupies.
15. **MCP security research validates the entire premise.** OWASP MCP Top 10 MCP04:2025 is literally "Lack of Audit and Telemetry"; 30+ MCP CVEs were filed Jan–Feb 2026; rug-pull attacks (server changing tool descriptions mid-session) require runtime inspection at the proxy layer — exactly what AgentAudit's MCP proxy provides.

---

## C. Platform matrix

| Platform | Best capture path | Events available | Approval/HITL visible? | Solo feasible? | Fragility | Citations |
|---|---|---|---|---|---|---|
| **Cursor** | `hooks.json` (project `.cursor/` or `~/.cursor/`); supplement with SQLite `state.vscdb` scrape | `sessionStart/End`, `preToolUse/postToolUse/postToolUseFailure`, `before/afterShellExecution`, `before/afterMCPExecution`, `beforeReadFile/afterFileEdit`, `beforeSubmitPrompt`, `stop`, `afterAgentResponse/Thought` + Tab hooks | **Yes** — `beforeShellExecution`/`beforeMCPExecution` return `allow\|deny\|ask`; exit 2 = block | Yes | **High on Windows** (UTF-8 stdin corruption; WSL-bash PATH resolution; output-not-surfaced regressions). Cloud agents defer session/MCP hooks. | cursor.com/docs/hooks; forum threads |
| **Claude Code** | `settings.json` hooks (PreToolUse/PostToolUse/SessionStart/Stop/etc.); supplement with `~/.claude/projects/*.jsonl` scrape | 8 lifecycle events; MCP tools matched as `mcp__<server>__<tool>` | **Yes** — `permissionDecision: allow\|deny\|ask`; exit 2 blocks; `Notification` fires on permission waits | Yes | **Low–Medium** — Sept 2025 validation tightening disabled misconfigured hooks; otherwise stable | code.claude.com hooks docs; FrancisBourre gist |
| **Google Antigravity** | `.agents/hooks.json` (or `~/.gemini/config/`); SDK `Inspect` hooks for non-blocking observability; supplement with `transcript.jsonl` scrape | `PreToolUse/PostToolUse/PreInvocation/PostInvocation/Stop`; tools: `run_command`, `view_file`, `write_to_file`, `ask_permission`, `ask_question`, `invoke_subagent`, etc. | **Yes** — `ask_permission`/`ask_question` tools + declarative `confirm_run_command()`/`policy.deny()` Decide hooks | Yes (product new, docs thin but real) | **Low–Medium** — new product, hooks carried over from Gemini CLI (mature); camelCase field schema | antigravity.google/docs/hooks; google-antigravity SDK |

### Ranked capture strategies (consolidated, all platforms)

| Strategy | Feasibility | Completeness | Solo effort | Fragility | Notes |
|---|---|---|---|---|---|
| IDE lifecycle hooks | 5 | 5 | S | Med (Cursor Windows) | Primary path for all three; Cursor `before*` carries decisions |
| MCP stdio proxy / gateway | 5 | 4 | M | Low | One adapter covers all MCP-sourced tool calls across all 3 clients |
| Local transcript/log scrape | 4 | 4 | M | Med | JSONL (Claude, Antigravity) easy; SQLite (Cursor) needs schema reverse-eng |
| Network MITM proxy | 3 | 3 | M | High | Captures LLM API `tool_use` blocks, not local exec; ToS-OK with own API key |
| OS-level (ETW/auditd/ProcMon) | 2 | 1 | L | Low | Coarse process spawns only; no tool args; reject for audit fidelity |
| Enterprise admin API | 2 | 2 | M | Low | Governance events only (Cursor Enterprise); Purview Claude connector — not per-tool |
| Browser extension | 2 | 2 | M | High | Web Claude only; out of scope for IDE agents |

---

## D. Forum & community evidence

| # | URL | Date | Platform | Summary | Relevance to Tier B |
|---|---|---|---|---|---|
| 1 | forum.cursor.com/t/native-posttooluse-hooks-accept-and-log-additional-context…/155689 | Mar 2025 | Cursor | Confirms native `postToolUse` hook in `.cursor/hooks.json` runs, returns `additional_context`; bug is that injected context isn't surfaced to model | Validates `postToolUse` as real event; audit capture works even if context injection doesn't |
| 2 | forum.cursor.com/t/hooks-intermittently-non-functional-on-windows…/154608 | 2025 | Cursor (Windows) | `preToolUse` worked then stopped after `hooks.json` edit; fix = delete hooks.json, recreate from scratch | Windows hook-state corruption; adapter must be idempotent/resilient |
| 3 | forum.cursor.com/t/windows-cursor-hooks-corrupt-chinese-utf-8-characters…/142878 | 2025 | Cursor (Windows) | Non-ASCII UTF-8 chars in stdin JSON replaced with `?` (0x3F) before reaching the script | **Critical for hashing**: corrupt args → wrong `input_hash`; operator must hash pre-stdin or handle encoding |
| 4 | forum.cursor.com/t/hooks-still-not-working-properly-in-2-1-6/143417 | 2025 | Cursor | v2.1.6 regression: hook output not arriving in agent context; "Cursor NOT obeying its own spec"; Windows 10/11 | Fragility flag — pin Cursor versions in CI for the adapter |
| 5 | forum.cursor.com/t/cursor-cli-hooks/148511 | 2025 | Cursor | Feature request listing `afterShellExecution, afterMCPExecution, afterFileEdit, afterAgentResponse, afterAgentThought` as "observe-only per spec" | Confirms `after*` hooks are observe-only (audit-only) — exactly right for recording, wrong for gating |
| 6 | github.com/obra/superpowers/issues/912 | 2025 | Cursor (Windows) | `SessionStart` hook fails because PATH `bash` resolves to `C:\Windows\System32\bash.exe` (WSL launcher); needs Git-for-Windows bash | Concrete Windows fix: invoke `C:\Program Files\Git\bin\bash.exe` explicitly |
| 7 | gist.github.com/johnlindquist/… (claude-code-vs-cursor-hooks.md) | 2025 | Cross | Side-by-side schema map: Claude `session_id` ↔ Cursor `conversation_id`; `tool_name`/`tool_input` identical; `cwd`+`CLAUDE_PROJECT_ROOT` ↔ `workspace_roots[]`+`CURSOR_PROJECT_DIR` | Direct field-mapping source for the normalizer |
| 8 | reddit.com/r/LocalLLaMA/…/finally_got_observability_working_for_claude_code_and_cursor | 2025 | Cross | Practitioner built real-time agent tracing using Cursor `~/.cursor/hooks.json` (~7 lifecycle events) + Claude Code hooks | Community proof both are instrumentable for tracing |
| 9 | reddit.com/r/cursor/…/how_do_you_keep_track_of_your_prompts | 2025 | Cursor | "Cursor offers hooks… structured audit-logging also becomes pretty easy with that" | Validates hooks-as-audit-path community sentiment |
| 10 | github.com/disler/claude-code-hooks-mastery | 2025 | Claude Code | Open repo mastering Claude Code hooks: payloads, error codes, UserPromptSubmit deep-dive, sub-agents, team validation | Reference implementation for Claude adapter |
| 11 | gist.github.com/FrancisBourre/…/claude-code-hooks-schemas.md | Aug 2025 | Claude Code | Authoritative stdin/stdout schemas for all 8 hook events, exit-code-2 matrix, MCP tool naming | Schema source for Claude field mapping |
| 12 | github.com/anthropics/claude-code/issues/6305 | Sep 2025 | Claude Code | Sept 2025 validation tightening: invalid `settings.json` disables hooks entirely | Adapter must emit strictly-valid config or hooks silently die |
| 13 | github.com/google-antigravity/antigravity-sdk-python/…/hooks/README.md | Jun 2026 | Antigravity | Inspect/Decide/Transform taxonomy; TOCTOU-safe Decide→exec→Inspect; Session/Turn/Operation context hierarchy | Confirms Antigravity is the most rigorously-designed hook system of the three |
| 14 | medium.com/google-cloud/a-developers-guide-to-agent-hooks-in-antigravity-cli | 2025 | Antigravity | Hooks carried over from Gemini CLI to Antigravity CLI; stdin/stdout/exit-code (0/2/other) semantics | Gemini CLI maturity underpins Antigravity hooks |
| 15 | dev.to/…/skills-over-system-prompts-building-an-anki-tutor-with-antigravity-sdk | 2025 | Antigravity | Uses `policy.confirm_run_command()` + `policy.deny("rate_card")` for runtime tool blocking | Declarative deny = approval/deny events capturable in Antigravity |
| 16 | github.com/mksglu/context-mode/issues/46 | Mar 2026 | Cross | "Five of six major platforms now support lifecycle hooks" (Claude Code, Gemini/Antigravity, OpenCode, Copilot CLI, Cursor); only Codex lacks them | Industry validation; hooks are the standard capture surface |
| 17 | github.com/chouzz/llm-interceptor | 2025 | Cross | CLI tool intercepting Claude Code/Cursor/Codex/OpenCode ↔ LLM APIs; multi-provider; auto-masks keys; SSE + non-streaming | Prior art for the MITM-capture strategy |
| 18 | localai.io/features/mitm-proxy | 2025 | Cross | LocalAI HTTPS proxy redacts PII from Claude Code/Codex; allowlists `api.anthropic.com`/`api.openai.com`; works with Pro/Max subscription | ToS-safe MITM with PII redaction — relevant pattern |
| 19 | news.ycombinator.com/item?id=46549823 | 2025 | Claude Code (HN) | Anthropic blocks third-party use of Claude Code subscriptions; Claude Code closed-source, no 3rd-party OpenAI-compatible APIs | ToS boundary: relaying subscription = prohibited; local hooks = fine |
| 20 | c-sharpcorner.com/…/intercepting-and-decoding-claude-code-api-calls-using-mitm-proxy | 2025 | Claude Code | Walkthrough intercepting Claude Code's 80KB Messages API payload, decoding the agent loop/tool calls via mitmproxy | Proves tool calls reconstructable from API stream |
| 21 | monad.com/blog/cursor-audit-logs-whats-emitted-and-detection-opportunities | Jul 2026 | Cursor (enterprise) | Cursor Admin API audit logs (Enterprise only): logins, roles, MCP-config/hook changes, spend — NOT per-tool invocations | Defines the enterprise-tier ceiling; tool calls still need hooks |
| 22 | owasp.org/www-project-mcp-top-10 | 2025 | MCP (cross) | MCP04:2025 = "Lack of Audit and Telemetry" | Directly names AgentAudit's mission as a top-10 MCP risk |

---

## E. Gap analysis vs operator schema

- **`tool.input_hash` (SHA-256 of redacted args):** Cursor's Windows UTF-8 stdin corruption means the hash may be computed over already-corrupted bytes — the adapter must hash inside the hook process *after* re-reading raw bytes, or Cursor must fix encoding. Claude Code and Antigravity pass clean JSON. None of the three expose a native arg hash — the operator must compute it (correct design).
- **`approval_request` / HITL:** All three expose it, but via different surfaces — Cursor `before*` hooks (`ask` decision), Claude Code `PreToolUse` `permissionDecision:"ask"` + `Notification` event, Antigravity `ask_permission`/`ask_question` tools + Decide hooks. No platform emits a discrete "human clicked approve" event with timestamp+identity; the operator must infer approval from the transition `ask`→`postToolUse` (tool proceeded) vs `ask`→no-postToolUse (denied/aborted).
- **`initiator` (human vs autonomous):** None of the three tag turns as human-initiated vs agent-initiated in the hook payload. Cursor's `beforeSubmitPrompt` (human typed) vs `afterAgentThought` (agent self-directed) can be correlated; Claude Code's `UserPromptSubmit` vs agent-driven `PreToolUse` similarly. This is an inference, not a native field — a hard gap for clean attribution.
- **Model/provider id:** Cursor hooks do **not** include the model name in stdin (only `conversation_id`/`generation_id`/`tool_input`). Claude Code's hook envelope omits model id (it's in the transcript JSONL, not stdin). Antigravity's hook input doesn't surface model id either. The operator must scrape transcripts or MITM the API to get model/provider — a real gap for the hook-only path.
- **`correlation_id` consistency:** Cursor = `conversation_id`; Claude Code = `session_id`; Antigravity = `conversationId` (camelCase). All map to `correlation_id` via the normalizer — no gap, but field-name translation is required per-platform.
- **Approval identity (who approved):** No platform records which human user approved a tool call in the hook payload. On a single-operator Windows machine this is implicit; multi-user/enterprise needs the Admin API (Cursor Enterprise) or IdP correlation — inaccessible to a solo local recorder.
- **Post-execution result/exit-code of the tool:** Cursor `afterShellExecution`/`afterMCPExecution` are observe-only but the docs don't confirm they include the tool's stdout/exit status. Claude Code `PostToolUse` includes `tool_response`. Antigravity `PostToolUse` Inspect hooks receive execution context. Operator should treat tool-result capture as reliable only on Claude/Antigravity, partial on Cursor.
- **Plaintext args (PII risk):** All three pass plaintext `tool_input`/args over stdin. The operator's redaction-before-hash is the correct mitigation and is **not** provided by any platform natively — this is the operator's value-add and a GDPR necessity.

---

## F. Implementation brief for Cursor

**Verdict:** The operator's existing event set is valid but incomplete. Add the `before*` gating events to capture allow/deny/ask decisions; harden Windows encoding; hash inside the hook process.

### Corrected `.cursor/hooks.json`

See repo `.cursor/hooks.json` — includes `beforeShellExecution`, `beforeMCPExecution`, `preToolUse`, `after*`, `postToolUse`, `stop`.

### Windows hardening checklist

- Invoke hooks via `python.exe` directly — never rely on PATH `bash` (resolves to WSL launcher, breaks `sessionStart`).
- Hash args **inside** the Python process from `sys.stdin.buffer.read()` — Cursor corrupts non-ASCII before stdin.
- Keep hook runtime < 30s; use 2s ingest timeout and fail-open (exit 0).
- Pin Cursor version in CI — v2.1.6 had hook-output-not-surfaced regression.
- Cloud agents defer `sessionStart/End` and MCP hooks in read-only mode — document capture blind spot.

### Reject list (Cursor)

- OS-level ETW/ProcMon for tool args — too coarse, no `tool_input`.
- Relying on Cursor Admin API for per-tool audit — Enterprise-only and governance-level only.
- Prompt-based hooks for audit — non-deterministic, unsuitable for a flight recorder.

---

## G. Implementation brief for Claude Code

**Verdict:** Highest-fidelity, lowest-effort adapter. Wire `PreToolUse` + `PostToolUse` + `SessionStart` + `Stop` in `~/.claude/settings.json`.

See repo `adapters/claude/settings.agentaudit.json`.

### Notes

- `permissionDecision` is an *output* the hook returns to steer Claude; to **observe** approvals, read `Notification` and correlate `PreToolUse(ask)` → `PostToolUse` (approved+ran) vs no-PostToolUse (denied).
- Settings validation tightened Sept 2025 — invalid JSON silently disables all hooks.
- Supplement/fallback: tail `~/.claude/projects/<encoded-path>/<session-id>.jsonl`.
- ToS: local hooks on your own machine for your own audit are permitted. Do **not** relay Pro/Max subscription credentials through a third-party proxy for other users.

### Reject list (Claude)

- Routing subscription OAuth through a MITM for multi-tenant audit — ToS violation.
- Relying solely on `--dangerously-skip-permissions` runs — approvals are skipped, so `approval_request` events never fire.

---

## H. Implementation brief for Antigravity

**Verdict:** Promote from "speculative" to P1. Documented `hooks.json` at `.agents/` (or `~/.gemini/config/`), five events, tool-name matchers, Inspect/Decide/Transform taxonomy.

See repo `adapters/antigravity/hooks.agentaudit.json`.

### Notes

- Antigravity exit codes mirror Gemini CLI: `0`=success, `2`=system block, other=warning.
- `transcriptPath` points to `<app_data_dir>/brain/<conversationId>/.system_generated/logs/transcript.jsonl`.
- SDK path gives `PostToolCallHook` (Inspect, async) and `PreToolCallDecideHook` (Decide) for SDK-driven runs.
- Declarative policies (`policy.confirm_run_command()`, `policy.deny(...)`) fire as Decide hooks — capture as `approval_request` with `decision: deny`.
- Telemetry: OpenTelemetry export to Google Cloud Trace/Monitoring/Logging — alternative enterprise export path.

### Reject list (Antigravity)

- Assuming the IDE exposes model id in hook payload — not confirmed; needs hands-on test.
- Treating Antigravity as "example JSON only" — outdated; hooks system is documented and SDK-backed.

---

## I. Competitive positioning

AgentAudit Tier B occupies the white-space between **SDK-instrumented observability** (Langfuse, Arize Phoenix, Helicone — self-hostable, but require in-process instrumentation of *your* agent code and capture nothing from external IDE agents) and **network-layer CASB/SSPM** (Microsoft Purview's Claude connector, Netskope, Zscaler — DNS/TLS metadata and governance events but blind to tool names, arguments, MCP servers, and approval decisions, and enterprise-only). Where NeMo Relay and llm-interceptor capture LLM API traffic, they reconstruct tool calls from the stream but miss local tool execution and approval/HITL state that only lifecycle hooks expose. AgentAudit's differentiator is the **vendor-neutral, local, hook-first flight recorder** that normalizes Cursor/Claude/Antigravity/MCP events into one append-only JSONL with hashed-redacted args and correlation IDs — a chain-of-custody surface no competitor provides out-of-the-box, and one that directly answers OWASP MCP Top-10 risk MCP04 ("Lack of Audit and Telemetry").

---

## J. Confidence & unknowns

**High confidence (primary-source verified):**

- Cursor, Claude Code, and Antigravity all ship documented lifecycle hooks with stdin JSON, exit-code blocking, and allow/deny/ask decisions.
- Claude Code and Antigravity transcript JSONL paths and shapes.
- Cursor Windows hook fragility (UTF-8 corruption, WSL-bash, 2.1.6 regression).
- Antigravity's Inspect/Decide/Transform taxonomy and declarative policies.
- OWASP MCP04 = lack of audit/telemetry; rug-pull runtime-inspection requirement.
- Langfuse/Phoenix self-hostable but SDK-instrumenting, not IDE-capturing.

**Medium confidence (single community source or inferred):**

- Exact field set in Cursor `afterShellExecution`/`afterMCPExecution` stdin (observe-only per spec but full stdin shape unconfirmed in official docs snippet).
- Whether Cursor `after*` hooks include the tool's exit code / stdout.
- Antigravity hook stdin field names (`tool_input` vs `toolInput` — docs use camelCase).

**Low confidence / needs hands-on testing:**

- Model/provider id availability in any hook payload — appears absent in all three.
- Whether Antigravity's `ask_permission`/`ask_question` tools fire `PreToolUse`/`PostToolUse` hooks or only surface in the transcript.
- Approval-denied path observability: no platform emits a clean "human denied" event; `ask`→no-`PostToolUse` inference needs validation.
- Antigravity IDE (2.0) vs CLI vs SDK hook parity.
- ToS edge case: whether running Claude Code hooks that POST to local ingest is explicitly blessed vs merely "not prohibited."
- GDPR: hashing-redacted args aligned with Art. 25; plaintext args transiting stdin inside hook process may still be "processing" — minimize dwell time.

**Recommended hands-on validation before P0 ship:** dump full stdin from one run of each hook event on all three platforms (Windows for Cursor), confirm field names, confirm `after*`/`PostToolUse` include tool results, and confirm approval-denied runs produce a distinguishable event sequence.
