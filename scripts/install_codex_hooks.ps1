# Install Agentmetry hooks for OpenAI Codex CLI - GLOBAL (~/.codex/hooks.json).
# Merges into your existing hooks; your own groups are preserved. Idempotent.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_codex_hooks.ps1
#
# NOT run at orchestrator boot, unlike Claude and Cursor. Codex gates hooks
# behind a trust prompt that only a human can complete, so an install nobody
# asked for would sit there looking installed and capturing nothing.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
# Prefer the orchestrator venv. `install.ps1` creates it and installs
# Agentmetry into it, but global python usually has no `agentmetry` module, so
# resolving `python` here failed with ModuleNotFoundError on a clean machine
# while the top-level installer still reported success (issue #137).
$VenvPython = Join-Path $RepoRoot "apps\orchestrator\.venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
$Bootstrap = Join-Path $RepoRoot "apps\orchestrator\agentmetry\core\audit\hook_bootstrap.py"

if (-not (Test-Path $Bootstrap)) {
    Write-Error "hook_bootstrap.py not found at $Bootstrap"
    exit 1
}

& $Python $Bootstrap codex

# A native command's exit code does NOT trip $ErrorActionPreference, so without
# this check the script would print the success message after a failed install.
# Every other installer in this directory did exactly that for months.
if ($LASTEXITCODE -ne 0) {
    Write-Error "Codex hook install FAILED (exit $LASTEXITCODE). Nothing was installed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.codex\hooks.json"
Write-Host ""
Write-Host "REQUIRED, and Agentmetry cannot do it for you:"
Write-Host "  Open Codex and run /hooks, then approve the Agentmetry entries."
Write-Host "  Codex trusts hooks by hash and skips untrusted ones SILENTLY, so"
Write-Host "  until you approve them this install captures nothing at all."
Write-Host ""
Write-Host "Then confirm coverage: agentmetry doctor"
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='codex'; python scripts/agentmetry_ingest.py selftest"
