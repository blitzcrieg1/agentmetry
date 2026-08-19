# Install Agentmetry hooks for Qoder (通义灵码) — GLOBAL (~/.qoder/settings.json).

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\agentmetry\core\audit\hook_bootstrap.py") qoder

# A native command's exit code does NOT trip $ErrorActionPreference, so
# without this the success message below printed after a failed install.
if ($LASTEXITCODE -ne 0) {
    Write-Error "qoder hook install FAILED (exit $LASTEXITCODE). Nothing was installed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.qoder\settings.json"
Write-Host "IMPORTANT: Fully QUIT Qoder once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='qoder'; python scripts/agentmetry_ingest.py selftest"
