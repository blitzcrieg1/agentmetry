# Install Agentmetry hooks for Claude Code — GLOBAL (~/.claude/settings.json).
# Merges into your existing settings (theme, permissions, MCP servers, env are
# preserved). Applies to every Claude Code project. Idempotent.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_claude_hooks.ps1
#
# Also runs automatically when the orchestrator boots.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\agentmetry\core\audit\hook_bootstrap.py")

# A native command's exit code does NOT trip $ErrorActionPreference, so
# without this the success message below printed after a failed install.
if ($LASTEXITCODE -ne 0) {
    Write-Error "claude hook install FAILED (exit $LASTEXITCODE). Nothing was installed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.claude\settings.json"
Write-Host "IMPORTANT: Fully QUIT Claude Code once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='claude'; python scripts/agentmetry_ingest.py selftest"
