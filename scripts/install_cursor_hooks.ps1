# Install AgentAudit hooks for Cursor — GLOBAL (~/.cursor/hooks.json).
# Applies to every Cursor workspace, not just this repo.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1
#
# Also runs automatically when the orchestrator boots.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\core\audit\hook_bootstrap.py")

Write-Host ""
Write-Host "Global hooks -> $env:USERPROFILE\.cursor\hooks.json"
Write-Host "IMPORTANT: Fully QUIT Cursor once, then reopen any project."
Write-Host "Preflight: `$env:AGENTAUDIT_SOURCE_APP='cursor'; python scripts/agentaudit_ingest.py selftest"
