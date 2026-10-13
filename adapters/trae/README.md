# Trae (ByteDance): partial Tier B coverage

The Trae IDE now documents lifecycle hooks
([Automate with hooks](https://docs.trae.ai/ide/automate-actions-with-hooks),
[Hook configuration reference](https://docs.trae.ai/ide/hook-configuration-reference)).
Agentmetry does not install or map them yet, so today only the MCP servers
you wrap are recorded.

What Trae's reference describes, checked 2026-10-13:

- Six hook event types, including `SessionStart`, `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse` and `Notification`, configured in a
  `hooks.json` that Trae creates for the hook scope you choose.
- JSON on stdin, a decision on stdout in Claude Code's shape:
  `hookSpecificOutput.permissionDecision`, with `allow`, `deny` and `ask`.
- Exit code 2 is equivalent to `"permissionDecision": "deny"`: the tool call
  does not run and stderr is passed to the model as the reason.

The open-source [trae-agent](https://github.com/bytedance/trae-agent) CLI is a
different program. Its hooks request,
[trae-agent #397](https://github.com/bytedance/trae-agent/issues/397), is
still open.

## Today

Wrap MCP servers with `agentmetry mcp-proxy` (in the package, no checkout
needed) and set:

```powershell
$env:AGENTMETRY_SOURCE_APP="trae"
agentmetry mcp-proxy -- your-mcp-server-command --its --arguments
```

Events arrive as `source.app: trae` via the MCP proxy adapter. Trae's
built-in tools are not seen.

## A hook adapter, when it is built

Trae's format is Claude-shaped, so the path is the Qwen and Kimi pattern in
`core/audit/hook_bootstrap.py`: add `trae` to `_CLAUDE_PROTOCOL` in
`agentmetry/hooks/ingest.py`, a mapper and an installer, and a row in
`SURFACES` (`core/diagnostics/hook_coverage.py`) so coverage attests it.
Two things to check against Trae itself before claiming enforcement:

- whether Trae honours a JSON `ask`, before adding it to `ASK_HONOURED`.
  Until then a policy ask is enforced as deny, which is the safe direction;
- that a JSON deny actually stops the tool. The Codex deny looked right and
  failed open until 0.9.5, which is why Codex's decisions are now tested
  against its published schema.

Track: [docs/agent-coverage.md](../../docs/agent-coverage.md),
[docs/integrations/chinese-agents.md](../../docs/integrations/chinese-agents.md)
