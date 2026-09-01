# Install Agentmetry hooks for Tencent CodeBuddy, GLOBAL (~/.codebuddy/settings.json).

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

& $Python (Join-Path $RepoRoot "apps\orchestrator\agentmetry\core\audit\hook_bootstrap.py") codebuddy

# A native command's exit code does NOT trip $ErrorActionPreference, so
# without this the success message below printed after a failed install.
if ($LASTEXITCODE -ne 0) {
    Write-Error "codebuddy hook install FAILED (exit $LASTEXITCODE). Nothing was installed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Global hooks merged -> $env:USERPROFILE\.codebuddy\settings.json"
Write-Host "IMPORTANT: Fully QUIT CodeBuddy once, then reopen any project."
Write-Host "Preflight: `$env:AGENTMETRY_SOURCE_APP='codebuddy'; python scripts/agentmetry_ingest.py selftest"
