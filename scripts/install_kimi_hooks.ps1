# Install Agentmetry hooks for Kimi Code — GLOBAL (~/.kimi-code/config.toml).
# Inserts a managed [[hooks]] block (other config.toml keys are preserved).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_kimi_hooks.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\core\audit\hook_bootstrap.py") kimi

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.kimi-code\config.toml"
Write-Host "IMPORTANT: Fully QUIT Kimi Code once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='kimi'; python scripts/agentmetry_ingest.py selftest"
