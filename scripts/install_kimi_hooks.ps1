# Install Agentmetry hooks for Kimi Code — GLOBAL (~/.kimi-code/config.toml).
# Inserts a managed [[hooks]] block (other config.toml keys are preserved).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_kimi_hooks.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\agentmetry\core\audit\hook_bootstrap.py") kimi

# A native command's exit code does NOT trip $ErrorActionPreference, so
# without this the success message below printed after a failed install.
if ($LASTEXITCODE -ne 0) {
    Write-Error "kimi hook install FAILED (exit $LASTEXITCODE). Nothing was installed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.kimi-code\config.toml"
Write-Host "IMPORTANT: Fully QUIT Kimi Code once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='kimi'; python scripts/agentmetry_ingest.py selftest"
