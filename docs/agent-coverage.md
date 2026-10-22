# Agent coverage

Checked 2026-10-13 against this tree and the vendor pages linked below.

**Agentmetry traces what an agent does on a machine you control, whichever model it runs on. It cannot see agents that live entirely in someone else's cloud.**

This is a research matrix, not a support list. A row is "supported and tested" only when this repo records it and a test exercises that path. Everything else is either a path someone could build or an honest "no". An agent that is absent from the tables is not supported.

## Recording is general. Detections are not.

Any agent that can reach `POST /api/v1/audit/ingest` can be recorded into the hash-chained trail. What the detections can do with those events depends on what arrives with them:

- **ATT&CK mapping is computed on the server** from the tool name and its arguments (`get_mitre_mapping`, called from `core/audit/external.py`) whenever the client sends none. Rules built on tactics, such as credential access followed by network egress, can fire for any integration whose tool names and arguments map.
- **Command traits are computed only by the client.** The hooks classify the shell command before hashing it (`classify_command` in `hooks/ingest.py`) and send the labels. The server keeps traits it is sent and computes none of its own. An integration that posts no traits gets no trait-based detections, such as `encoded-command-download` or `dotfile-read-then-git-push`. The CrewAI and OpenSRE adapters send no traits today.
- **The rules describe endpoint behaviour.** The published set ([detection-rules.md](detection-rules.md)) is about shell commands, credential files, network egress, git, cloud CLIs, deletions, subagents and approvals. A support bot that files a ticket or a workflow that posts to Slack gets a valid record and, almost always, no detection.

The "Detections apply?" column below uses three values: **yes** (the integration sends what the rules read), **partly** (the ATT&CK mapping applies, the trait-based rules do not, or only some of the agent's actions are endpoint actions), and **record only** (the rules have nothing to match).

## How to read a row

| Status | Meaning |
| --- | --- |
| supported and tested | An installer, mapper or adapter in this repo, and tests that exercise it. |
| proxy as above | Only the stdio MCP servers you wrap with `agentmetry mcp-proxy` are recorded. The app's built-in tools are not. |
| possible, not built | The vendor documents a hook, plugin, event API or structured log. This repo has no installer and no mapper for it. |
| not traceable locally | The actions run on the vendor's computers. A recorder on your machine has nothing to attach to. |

"Unverified" marks a claim that was not confirmed against a primary source. It is a note, not a fifth status.

Deny and ask are narrower than recording. `ask_honoured()` in `core/audit/tool_policy/capability.py` trusts an ask only for Claude Code `PreToolUse` and for Cursor `beforeShellExecution` and `beforeMCPExecution`. Everywhere else a policy ask is enforced as deny, because an ask the agent ignores is an allow.

Two lists in the code bound every "supported" claim:

- `SURFACES` in `core/diagnostics/hook_coverage.py` is what `doctor` and the heartbeat attest: `cursor`, `claude`, `qwen`, `qoder`, `codebuddy`, `kimi`, `codex`, `copilot`, `antigravity`.
- `KNOWN_EXTERNAL_APPS` in `core/audit/external.py` is what the ingest API keeps as `source.app`: the nine above plus `mcp_proxy`, `trae`, `crewai` and `opensre`. Any other `source_app` is recorded as `unknown`, with the claimed name kept in `source.claimed_app`. A new integration still needs an allowlisted name to be attributed properly.

## A. Agentic IDEs and coding CLIs

Captured through the agent's own hooks. Detections apply: **yes** for the nine hooked surfaces, because the hook sends traits and the ATT&CK block.

| Agent | How it is or could be captured | Status | Source |
| --- | --- | --- | --- |
| Claude Code | Hooks, with deny and ask on `PreToolUse`. Second path: `agentmetry otel`, record only. | supported and tested | [Hooks](https://code.claude.com/docs/en/hooks) |
| Cursor | Hooks. Ask honoured on `beforeShellExecution` and `beforeMCPExecution`. | supported and tested | [Hooks](https://cursor.com/docs/hooks) |
| Codex CLI | Hooks in `~/.codex/hooks.json`, after `/hooks` trusts them. Approval applies to conversations started afterwards. On Windows the installer writes the command unquoted, and never uses Codex's `commandWindows` override, which Codex's approval never matches ([#307](https://github.com/blitzcrieg1/agentmetry/issues/307)). Deny, no ask. | supported and tested | [Hooks](https://developers.openai.com/codex/hooks) |
| Antigravity | Hooks. Windows install script only. | supported and tested | [Hooks](https://antigravity.google/docs/hooks/) |
| Qwen Code | Claude-shaped hooks. | supported and tested | [Hooks](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/) |
| Kimi Code | Hooks in `~/.kimi-code/config.toml`, plus print-mode `stream-json`. | supported and tested | [Hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html) |
| Qoder | Claude-shaped hooks. | supported and tested | [Hooks](https://docs.qoder.com/cli/hooks) |
| CodeBuddy | Claude-shaped hooks (vendor docs marked beta). | supported and tested | [Hooks](https://www.codebuddy.ai/docs/cli/hooks) |
| Windsurf (Cascade) | Hooks. A pre-hook blocks with exit code 2. | possible, not built | [Cascade hooks](https://docs.devin.ai/desktop/cascade/hooks) |
| Trae | Claude-shaped hooks: `hookSpecificOutput.permissionDecision` (allow, deny, ask), exit code 2 as deny. | possible, not built | [Hooks](https://docs.trae.ai/ide/automate-actions-with-hooks), [reference](https://docs.trae.ai/ide/hook-configuration-reference) |
| Gemini CLI | Hooks in `settings.json` (`BeforeTool` and others). A different program from Antigravity. | possible, not built | [Hooks](https://geminicli.com/docs/hooks/) |
| GitHub Copilot, CLI and VS Code agent mode | One hooks file in `~/.copilot/hooks/` serves both. Deny is exit code 2. `--managed` writes the CLI's root-owned policy hooks. | supported and tested | [Hooks reference](https://docs.github.com/en/copilot/reference/hooks-reference), [VS Code hooks](https://code.visualstudio.com/docs/agent-customization/hooks) |
| Grok Build | Local CLI. Hooks in `~/.grok/hooks/*.json`. Deny is `{"decision":"deny"}` or exit code 2. | possible, not built | [Hooks](https://docs.x.ai/build/features/hooks) |
| Goose | Session database that stores tool calls, plus stdio MCP extensions. | possible, not built | [Logging](https://github.com/block/goose/blob/main/documentation/docs/guides/logs.md) |

Notes that keep the status honest:

- **GitHub Copilot.** The CLI and VS Code read the same `~/.copilot/hooks/*.json` and disagree on the JSON: the CLI reads a flat `permissionDecision`, VS Code only the nested `hookSpecificOutput` one (checked in microsoft/vscode `chatHookService.ts`). So the deny is exit code 2, which both document as a deny; VS Code fails open on any other non-zero code. Ask is enforced as deny. VS Code hooks are marked preview, an organisation can turn them off, and `chat.useHooks: false` turns them off locally, which `agentmetry posture` reports. Whether VS Code reads the CLI's policy hooks is not documented. Tests check both payload shapes and the exit code; neither surface was run live.
- **Codex.** Deny was broken until [#246](https://github.com/blitzcrieg1/agentmetry/pull/246): Codex was sent Cursor's `{"permission": ...}`, rejected it as an unknown field, and ran the tool while the trail recorded `denied`. Fixed on `master`, shipping in 0.9.5. **0.9.4 and earlier fail open on Codex.** Codex parses `ask` and runs the tool, so a policy ask is sent as deny. Hosted tools such as `WebSearch` do not fire `PreToolUse`. Shell, unified exec, `apply_patch`, MCP and other local function tools do.
- **Antigravity.** `agentmetry hooks install` does not write these hooks; `scripts/install_antigravity_hooks.ps1` does, on Windows. A public forum thread reports that the IDE and the 2.0 desktop app do not run `PreToolUse` while the CLI does. Unverified against a vendor statement.
- **Qwen, Qoder, CodeBuddy.** They get Claude's `hookSpecificOutput` (`_CLAUDE_PROTOCOL`). Their docs document ask, but `ask_honoured` does not include them, so a policy ask is enforced as deny. CodeBuddy has no mapping test of its own.
- **Kimi Code.** The installer writes `~/.kimi-code/config.toml`, the path on the kimi.com page. Moonshot's [kimi-cli](https://www.kimi-cli.com/en/customization/hooks.html) uses `~/.kimi/config.toml`. Whether that is the same program was not established.
- **Windsurf.** `mcp_inventory` reads its MCP config and records nothing. Installer work is parked in issue #7.
- **Trae.** `trae` is allowlisted for the MCP proxy. No mapper and no hook installer; [adapters/trae](../adapters/trae/README.md) says what one needs.
- **Gemini CLI.** It shares `~/.gemini` with Antigravity. Until the fix listed below, coverage read that directory as Antigravity being installed, so a machine with only Gemini CLI showed an uncovered Antigravity.
- **Grok Build.** Its docs say it also reads Claude Code settings and Cursor `hooks.json`. Whether an Agentmetry hook installed for those runs under Grok Build was not tested, and its deny shape differs from both, so a hook that ran would not prove a working deny.
- **Goose.** `sessions.db` holds tool-call ids, arguments, responses and outcomes. That is an after-the-fact import, not a live hook.

## B. Autonomous agents that run on your machine

Always-on or task agents that use tools on the computer where their process lives. None of these names is allowlisted. Detections apply: **partly** if one were built today on the ingest API (ATT&CK from tool names, no traits), **yes** if its mapper classified commands the way the hooks do.

| Agent | How it could be captured | Status | Source |
| --- | --- | --- | --- |
| OpenClaw | Plugin hooks. `before_tool_call` can block or require approval. `after_tool_call` observes. | possible, not built | [Plugin hooks](https://docs.openclaw.ai/plugins/hooks), [reference](https://docs.openclaw.ai/plugins/hooks/reference) |
| Hermes Agent (Nous Research) | Shell and plugin hooks. `pre_tool_call` can block, or escalate to Hermes's approval gate. Outbound webhooks. Also an stdio MCP client. | possible, not built | [Event hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks) |
| Agent Zero | Extension points `tool_execute_before` and `tool_execute_after`. Whether the first can block: unverified. | possible, not built | [Extensions reference](https://github.com/agent0ai/agent-zero/blob/main/skills/a0-development/references/extensions.md) |
| OpenHands, local CLI and GUI | Claude-compatible `.openhands/hooks.json`. `PreToolUse` blocks with exit code 2. Tool names differ (`terminal`, not `Bash`). | possible, not built | [Hooks](https://docs.openhands.dev/openhands/usage/customization/hooks) |
| Open Interpreter | Runs code on the local machine with a confirmation prompt. No hook or structured action log was found in current docs. Unverified. | unverified | [Project](https://github.com/openinterpreter/open-interpreter) |

Integration paths, for later issues. Not built, and not support claims:

- **OpenClaw.** An in-process plugin on `before_tool_call` and `after_tool_call` that posts to ingest. `HOOK.md` handlers are session lifecycle, not the tool boundary.
- **Hermes.** A shell `pre_tool_call` / `post_tool_call` entry is the closest thing to an IDE hook installer. `{"action":"block"}` is a real deny.
- **Agent Zero.** An extension at those two points.
- **OpenHands.** A hook installer and a mapper. OpenHands Cloud loads the same hooks in the cloud, which is category G.

## C. Computer-use and browser agents running locally

Agents that drive a browser or a desktop on your machine. A click, a keystroke and a page load are not tool calls a hook sees unless the agent routes them through a tool. Detections apply: **partly**. `untrusted-input-then-risky-action` is written for agents that read external content, but the shell and credential rules see nothing of a browser session.

| Agent | How it could be captured | Status | Source |
| --- | --- | --- | --- |
| Playwright MCP | An stdio MCP server (`npx @playwright/mcp`). Wrap it and every browser tool call is recorded. | proxy as above | [Repository](https://github.com/microsoft/playwright-mcp) |
| Browser Use | `on_step_start` and `on_step_end` hooks on `agent.run()`. The hook gets the agent and its browser session. They observe a step; they are not documented as a deny. | possible, not built | [Hooks](https://docs.browser-use.com/open-source/customize/hooks) |
| Claude computer use, in your own loop | The API returns the action and your code performs it, so your loop is the place to record. Same as category E. | possible, not built | [Computer use tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) |
| Claude Desktop computer use | Built-in tools, not stdio MCP. The proxy does not see them. | not covered | See category D |
| Stagehand, Skyvern (self-hosted) | Libraries and services that run a browser where you deploy them. Hook points not checked. | unverified | |

## D. Desktop assistants and MCP clients

Any app that launches stdio MCP servers can be recorded by wrapping each one:

```bash
agentmetry mcp-proxy -- <server command>
```

The proxy is supported and tested (`agentmetry/hooks/mcp_proxy.py`, `tests/test_mcp_audit_proxy.py`). It logs every stdio `tools/call` and fingerprints `tools/list`. HTTP, SSE and streamable HTTP are not proxied. Tools the app runs itself are invisible to it. `agentmetry mcp` inventories Claude, Cursor, Windsurf and VS Code configs; inventory is not capture. Detections apply: **partly**, depending on the servers. A filesystem or shell server maps; a calendar server does not.

| Client | How it could be captured | Status | Source |
| --- | --- | --- | --- |
| Any stdio MCP client | Wrap each server command. | supported and tested (the proxy) | `agentmetry/hooks/mcp_proxy.py` |
| Claude Desktop | Same wrap. Cowork and Chat also load plugin hooks, which this repo does not install. | proxy as above. Hook installer possible, not built | [Plugins and hooks](https://claude.com/docs/third-party/claude-desktop/extensions) |
| VS Code | Same wrap. `mcp.json` is already inventoried. | proxy as above | [MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers) |
| LM Studio | Host since 0.3.17. `mcp.json` in Cursor's notation, launched locally. Not in the inventory reader. | proxy as above | [MCP in LM Studio](https://lmstudio.ai/docs/app/mcp) |
| Jan | STDIO, HTTP and SSE transports. Jan Agent reads the same `mcp_config.json`. | proxy as above (STDIO only) | [MCP servers](https://jan.ai/docs/desktop/integrations/mcp-servers) |
| ChatGPT desktop app | Custom MCP connectors are remote HTTPS servers (Developer Mode). Local stdio servers are not run. From secondary sources; unverified against OpenAI's docs. | not traceable locally | See category G |

Wrapping a server and also installing a host hook records the same MCP call twice if both fire.

## E. Agents you build (frameworks)

The process runs where you deploy it, so capture is an adapter in that process that posts to the ingest API. Detections apply: **partly** for the two shipped adapters (server-side ATT&CK mapping only, no traits), and the same for any new one unless it classifies commands too.

| Framework | Hook point | Can it block a tool? | Status | Source |
| --- | --- | --- | --- | --- |
| CrewAI | Event bus: `ToolUsageStartedEvent`, `ToolUsageFinishedEvent`, `ToolUsageErrorEvent`. | Adapter records only | supported and tested | [Event listeners](https://docs.crewai.com/v1.15.24/en/concepts/event-listener) |
| OpenSRE | `Agent(..., on_runtime_event=...)`. | Adapter records only | supported and tested | [core/events.py](https://github.com/Tracer-Cloud/opensre/blob/main/core/events.py) |
| LangChain / LangGraph | `BaseCallbackHandler.on_tool_start` / `on_tool_end` on the runnable config. | Not established | possible, not built | [callbacks/base.py](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/callbacks/base.py) |
| OpenAI Agents SDK | `RunHooks` / `AgentHooks` `on_tool_start` and `on_tool_end`, or a custom `TracingProcessor`. | Not established | possible, not built | [Lifecycle](https://openai.github.io/openai-agents-python/agents/) |
| Microsoft Agent Framework | Function middleware around every tool call. | Yes: `MiddlewareTermination`, or not calling `call_next()` | possible, not built | [Middleware](https://learn.microsoft.com/en-us/agent-framework/agents/middleware/) |
| Semantic Kernel | Function invocation filter around every `KernelFunction`. | Yes: a filter that does not call `next` stops the function | possible, not built | [Filters](https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/filters) |
| AutoGen | Reported to be in maintenance mode, with Microsoft Agent Framework as the successor. From secondary sources; unverified. | | see Agent Framework | [Repository](https://github.com/microsoft/autogen) |
| Google ADK | `before_tool_callback` and `after_tool_callback`. | Yes: returning a dict from `before_tool_callback` skips the tool (per Google Cloud's copy of the ADK reference) | possible, not built | [Callback types](https://adk.dev/callbacks/types-of-callbacks/) |
| Pydantic AI | `before_tool_execute`, `tool_execute` (wrap), `after_tool_execute`, `tool_execute_error`. | Yes: `SkipToolExecution`; `ApprovalRequired` defers to a human | possible, not built | [Hooks](https://pydantic.dev/docs/ai/core-concepts/hooks/) |
| smolagents (Hugging Face) | `step_callbacks`, run at the end of each step, after the action executed. | No: it runs after the action | possible, not built | [Agents reference](https://huggingface.co/docs/smolagents/main/en/reference/agents) |
| LlamaIndex | `AgentWorkflow` streams `ToolCall` and `ToolCallResult` events. The instrumentation dispatcher takes event handlers. | Not established | possible, not built | [Streaming](https://developers.llamaindex.ai/python/framework/understanding/agent/streaming/) |
| Agno | `tool_hooks` (middleware around each call) and `pre_hook` / `post_hook` on `@tool`. | Yes: a tool hook can raise or return its own result instead of calling the tool | possible, not built | [Tool hooks](https://docs.agno.com/tools/hooks) |
| Mastra | `onStepFinish` exposes tool calls and results per step. Tracing records tool spans. A per-call hook was not found. | Not established | possible, not built | [Tracing](https://mastra.ai/docs/observability/tracing/overview) |
| Vercel AI SDK | A tool's `execute` is your function, so a wrapper can record and refuse. AI SDK 6 added `needsApproval`. From secondary sources; unverified against ai-sdk.dev. | Yes, in your own wrapper | possible, not built | [AI SDK](https://ai-sdk.dev/docs) |

Notes:

- **Blocking is not a promise.** "Yes" means the framework documents a way for code at that point to stop the tool. Agentmetry's framework adapters are recorders. A blocking adapter would be new work, and a deny that the framework then ignores would repeat the Codex failure.
- **Microsoft Agent Governance Toolkit files** are a separate, shipped path: `agentmetry import-agt` reads a `FileAuditSink` JSONL file after the file's own chain verifies, tested in `test_agt_adapter.py`. It imports a file some other runtime wrote. It does not make Semantic Kernel, Agent Framework, LangGraph or CrewAI supported on their own.
- **Where the framework runs matters.** A LangGraph graph on your server is this category. The same graph on a vendor's hosted platform is category G.

## F. Self-hosted agent and workflow platforms

Platforms where you build an agent in a visual editor and run it on your own servers. Capture would be a receiver that maps the platform's events into ingest. Detections apply: **record only**, mostly. Their tools are usually SaaS API calls (mail, chat, CRM), not endpoint actions.

| Platform | How it could be captured | Status | Source |
| --- | --- | --- | --- |
| n8n | Log streaming to a webhook or syslog. Event types include AI node events, among them a tool-called event. Enterprise licence. Whether events carry arguments: unverified. | possible, not built | [Log streaming](https://docs.n8n.io/log-streaming/) |
| Dify | OpenTelemetry export on self-hosted (`ENABLE_OTEL` and an OTLP endpoint). Whether each tool call is its own span: unverified. | possible, not built | [Dify](https://github.com/langgenius/dify) |
| Langflow | Tracing through Langfuse, Opik and others. A native tool-call hook was not found. | unverified | [Langfuse integration](https://langfuse.com/integrations/no-code/langflow) |
| Flowise | Analytics through Langfuse and others. A native tool-call hook was not found. | unverified | [Analytics](https://docs.flowiseai.com/using-flowise/analytics/langfuse) |

`agentmetry otel` is an OTLP receiver for Claude Code's event shape only. Several platforms here and in category G export OpenTelemetry, so a general OTLP mapping would open several rows at once. That is a design question, not a claim.

## G. Hosted agents (vendor cloud only)

A local recorder cannot trace these. Where the vendor keeps its own log, that is the customer's record, not an Agentmetry trail. The last column says whether that log holds tool-level actions or only administrative events, as far as was checked.

### Consumer and team apps

| Agent | Vendor's own logs |
| --- | --- |
| Grok app (grok.com, iOS, Android) | [Management API audit logs](https://docs.x.ai/developers/rest-api-reference/management/audit) are administrative. Custom MCP must be a public URL; localhost is rejected. A tool-call log was not found. |
| @bot on X, Grok Bot cloud computer | Work runs on the Bot's cloud computer. Enterprise [Action Recording](https://docs.x.ai/grok-bot/security) is off by default and exported over OpenTelemetry. Audit logs on that page are control-plane events. Optional local execution has no documented hook. |
| @grok on X | An action log was not found. Unverified. |
| ChatGPT, including ChatGPT agent | Enterprise and Edu: the Compliance Logs Platform. [OpenAI's agent article](https://help.openai.com/en/articles/11752874-chatgpt-agent) says agent conversations appear in Compliance API logs, but individual actions (virtual computer use, app requests) do not. A consumer export was not found. |
| Claude.ai | Enterprise: the [Compliance API](https://platform.claude.com/docs/en/manage-claude/compliance-api) returns conversation content and activity events (sign-ins, admin and configuration changes, MCP server configuration). A tool-call log was not found. |
| Gemini app, Perplexity, Manus | Not checked. |

### Enterprise agent platforms

| Agent | Vendor's own logs |
| --- | --- |
| Microsoft Copilot Studio agents | [Microsoft Purview audit](https://learn.microsoft.com/en-us/microsoft-copilot-studio/admin-logging-copilot-studio): admin activity plus maker and user interactions with agents, also through the Office 365 Management API. Some channels are not logged. Tool-level event names: unverified. |
| Salesforce Agentforce | Session Tracing Data Model in Data 360. The [Session Trace OTel API](https://developer.salesforce.com/docs/ai/agentforce/guide/otel-api) (beta) returns turns, LLM calls and actions per session: one session per request, last 72 hours. |
| Gemini Enterprise | Cloud Audit Logs plus [usage audit logs](https://docs.cloud.google.com/gemini/enterprise/docs/set-up-usage-audit-logs), which identify the agent that handled a request. Tool-level detail: unverified. |
| ServiceNow AI agents | Not checked. |

### Hosted coding agents

| Agent | Vendor's own logs |
| --- | --- |
| Cursor Cloud Agents | [Compliance and monitoring](https://cursor.com/docs/enterprise/compliance-and-monitoring): audit logs do not include cloud agent runs. OpenTelemetry Export can deliver cloud agent logs. |
| Codex cloud tasks | Codex policy changes are in the workspace audit log. A tool-call trace was not established. |
| GitHub Copilot cloud agent | Hooks run inside the job's sandbox ([reference](https://docs.github.com/en/copilot/reference/hooks-reference)). Org audit log coverage of those calls: unverified. |
| Devin | Enterprise audit log API ([v3 examples](https://docs.devin.ai/api-reference/v3/usage-examples)). Which session actions it records: unverified. |
| OpenHands Cloud | Hooks load in cloud sessions and run where the session runs, so a recorder on a laptop does not see them. |

## What this check found, and where it went

- **Codex deny failed open.** Fixed by [#246](https://github.com/blitzcrieg1/agentmetry/pull/246), shipped in 0.9.5.
- **Gemini CLI read as Antigravity.** A `~/.gemini` directory made coverage report Antigravity as installed. Fixed: presence is now `~/.gemini/antigravity` or one of our hook files (`Surface.presence` in `core/diagnostics/hook_coverage.py`).
- **Unknown agents were labelled `cursor`.** Any `source_app` outside `KNOWN_EXTERNAL_APPS` was stored as `cursor`, so an event from a new integration was attributed to the wrong agent. Fixed: it is recorded as `unknown`, and the claimed name is kept in `source.claimed_app` (`_resolve_source_app` in `core/audit/external.py`). A missing `source_app` still means Cursor, for hooks that predate the field.
- **Two stale docs.** `adapters/trae/README.md` and `docs/integrations/chinese-agents.md` said Trae ships no lifecycle hooks, and `docs/agentmetry-external-ingest.md` said Codex hooks may miss unified exec and some MCP. Both corrected against the vendors' pages on 2026-10-13.
