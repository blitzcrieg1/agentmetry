# Trae (ByteDance) — partial Tier B coverage

[Trae](https://www.trae.ai/) does **not** ship lifecycle hooks yet
([trae-agent #397](https://github.com/bytedance/trae-agent/issues/397)).

## Today

Wrap MCP servers with `tools/mcp_audit_proxy.py` and set:

```powershell
$env:AGENTMETRY_SOURCE_APP="trae"
python tools/mcp_audit_proxy.py --server "your-mcp-command"
```

Events arrive as `source.app: trae` via the MCP proxy adapter.

## When ByteDance ships hooks

Follow the Qwen/Kimi pattern in `core/audit/hook_bootstrap.py`:
Claude-family JSON on stdin → `scripts/agentmetry_ingest.py trae hook <Event>`.

Track: [docs/integrations/chinese-agents.md](../../docs/integrations/chinese-agents.md)
