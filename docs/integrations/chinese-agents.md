# Chinese AI coding agents (Tier B)

Agentmetry records tool calls from **Qwen Code**, **Kimi Code**, **Qoder**, and
**CodeBuddy** using the same Tier B path as Claude Code and Cursor: lifecycle hooks → `scripts/agentmetry_ingest.py`
→ `POST /api/v1/audit/ingest` → JSONL trail + sequence detections.

Both products adopted the **Claude hook wire protocol** (JSON on stdin,
`PreToolUse` / `PostToolUse`, exit code 2 or `permissionDecision: deny` to block).

---

## Supported today

| Agent | `source_app` | Config file | Install |
|-------|--------------|-------------|---------|
| **Qwen Code** | `qwen` | `~/.qwen/settings.json` | `scripts/install_qwen_hooks.ps1` |
| **Kimi Code** | `kimi` | `~/.kimi-code/config.toml` | `scripts/install_kimi_hooks.ps1` |
| **Qoder** (通义灵码) | `qoder` | `~/.qoder/settings.json` | `scripts/install_qoder_hooks.ps1` |
| **CodeBuddy** (Tencent) | `codebuddy` | `~/.codebuddy/settings.json` | `scripts/install_codebuddy_hooks.ps1` |

Templates: `adapters/qwen/settings.agentmetry.json`, `adapters/qoder/settings.agentmetry.json`.
Kimi uses a managed TOML block from the installer.

**Also works without new code:** wrap MCP servers with `tools/mcp_audit_proxy.py` for
any MCP-capable host (Trae, etc.) — see
[external ingest](../agentmetry-external-ingest.md).

---

## Detection (Sprint B)

| Rule | Fires when |
|------|------------|
| `subagent-swarm-burst` | ≥5 `SubagentStart` events in one session (Kimi AgentSwarm, Qwen Agent Teams) |
| `credential-read-then-cloud-api` | Also matches `aliyun`, `tencentcloud`, `ossutil`, `coscmd` CLIs |

**DLP:** Tencent `AKID…` SecretId, Chinese provider `*_API_KEY=` assignments,
extended `agent_env_override` for Moonshot/DashScope/DeepSeek/Zhipu/MiniMax.

**Tool policy:** blocks `kimi --yolo`, `qwen -p`, `deepseek` weaponization; protects
`.qwen/`, `.qoder/`, `.codebuddy/`, `.kimi-code/` config writes.

---

## Qwen Code

1. Agentmetry orchestrator running on `:8000`
2. Install hooks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_qwen_hooks.ps1
```

3. Fully quit and reopen Qwen Code (`qwen` in any repo)
4. Preflight:

```powershell
$env:AGENTMETRY_SOURCE_APP="qwen"
python scripts/agentmetry_ingest.py selftest
```

5. Confirm trail:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/audit/tail?sources=qwen&limit=5"
```

Hook events include `SubagentStart` / `SubagentStop` for swarm detection.

Docs: [Qwen Code hooks](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/)

---

## Kimi Code

1. Agentmetry orchestrator running on `:8000`
2. Install hooks:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_kimi_hooks.ps1
```

3. Fully quit and reopen Kimi Code (`kimi`)
4. Preflight:

```powershell
$env:AGENTMETRY_SOURCE_APP="kimi"
python scripts/agentmetry_ingest.py selftest
```

The installer appends a marked `# agentmetry hooks begin` … `end` block with
`[[hooks]]` tables. Re-run the installer to update paths — it replaces the managed block only.

Docs: [Kimi Code hooks](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/hooks.html)

---

## Qoder (通义灵码)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_qoder_hooks.ps1
$env:AGENTMETRY_SOURCE_APP="qoder"; python scripts/agentmetry_ingest.py selftest
```

Docs: [Qoder hooks](https://docs.qoder.com/en/cli/hooks)

---

## CodeBuddy (Tencent)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_codebuddy_hooks.ps1
$env:AGENTMETRY_SOURCE_APP="codebuddy"; python scripts/agentmetry_ingest.py selftest
```

Docs: [CodeBuddy hooks](https://www.codebuddy.ai/docs/cli/hooks)

---

## Trae and IDE-only hosts

[Trae](https://www.trae.ai/) (ByteDance) and similar AI-native IDEs do **not** ship
lifecycle hooks yet ([trae-agent #397](https://github.com/bytedance/trae-agent/issues/397)).
Partial coverage: wrap MCP servers with `mcp_audit_proxy.py`.

**ROADMAP:** Kimi `stream-json` ingest, Trae hooks when ByteDance ships them.

---

## Forensics

For incident response on agent sessions, use
[local LLM forensics](../compliance/local-llm-forensics.md) — especially when
commercial APIs refuse to analyze payloads containing live credentials or exploit text.
