# Install AgentAudit hooks for Claude Code — GLOBAL (~/.claude/settings.json).
# Merges into your existing settings (theme, permissions, MCP servers, env are
# preserved). Applies to every Claude Code project. Idempotent.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
#
# Also runs automatically when the orchestrator boots.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\core\audit\hook_bootstrap.py")

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.claude\settings.json"
Write-Host "IMPORTANT: Fully QUIT Claude Code once, then reopen any project."
Write-Host "Preflight: `$env:AGENTAUDIT_SOURCE_APP='claude'; python scripts/agentaudit_ingest.py selftest"
