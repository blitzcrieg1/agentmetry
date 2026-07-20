# Install Agentmetry hooks for Qoder (通义灵码) — GLOBAL (~/.qoder/settings.json).

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\core\audit\hook_bootstrap.py") qoder

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.qoder\settings.json"
Write-Host "IMPORTANT: Fully QUIT Qoder once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='qoder'; python scripts/agentmetry_ingest.py selftest"
