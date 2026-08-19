# Install Agentmetry hooks for Cursor — GLOBAL (~/.cursor/hooks.json).
# Applies to every Cursor workspace, not just this repo.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_cursor_hooks.ps1
#
# Also runs automatically when the orchestrator boots.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source

& $Python (Join-Path $RepoRoot "apps\orchestrator\agentmetry\core\audit\hook_bootstrap.py")

# A native command's exit code does NOT trip $ErrorActionPreference, so
# without this the success message below printed after a failed install.
if ($LASTEXITCODE -ne 0) {
    Write-Error "cursor hook install FAILED (exit $LASTEXITCODE). Nothing was installed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Global hooks -> $env:USERPROFILE\.cursor\hooks.json"
Write-Host "IMPORTANT: Fully QUIT Cursor once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='cursor'; python scripts/agentmetry_ingest.py selftest"
