# Install Agentmetry hooks for Tencent CodeBuddy — GLOBAL (~/.codebuddy/settings.json).

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\core\audit\hook_bootstrap.py") codebuddy

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.codebuddy\settings.json"
Write-Host "IMPORTANT: Fully QUIT CodeBuddy once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='codebuddy'; python scripts/agentmetry_ingest.py selftest"
