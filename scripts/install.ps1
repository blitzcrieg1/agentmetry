# Agentmetry — Windows one-flow install (orchestrator + dashboard + IDE hooks).
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Options:
#   -SkipHooks      Do not install Cursor / Claude global hooks
#   -SkipDashboard  Skip npm install for apps\dashboard
#   -NoDoctor       Skip agentmetry doctor at the end

param(
    [switch]$SkipHooks,
    [switch]$SkipDashboard,
    [switch]$NoDoctor
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OrchRoot = Join-Path $RepoRoot "apps\orchestrator"
$DashRoot = Join-Path $RepoRoot "apps\dashboard"
$VenvPython = Join-Path $OrchRoot ".venv\Scripts\python.exe"
$VenvPip = Join-Path $OrchRoot ".venv\Scripts\pip.exe"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found on PATH: $Name"
    }
}

function Get-PythonVersion {
    $raw = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    return [version]$raw.Trim()
}

Write-Host ""
Write-Host "Agentmetry install" -ForegroundColor White
Write-Host "Repo: $RepoRoot"

Write-Step "Checking prerequisites"
Require-Command python
if (-not $SkipDashboard) {
    Require-Command node
    Require-Command npm
}

$pyVer = Get-PythonVersion
if ($pyVer -lt [version]"3.11") {
    throw "Python 3.11+ required (found $pyVer). Install from https://www.python.org/downloads/"
}
Write-Host "  Python $pyVer OK"

if (-not $SkipDashboard) {
    $nodeVer = (& node -v).TrimStart("v")
    Write-Host "  Node $nodeVer OK"
}

Write-Step "Creating orchestrator virtualenv"
Push-Location $OrchRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & python -m venv .venv
}
& $VenvPython -m pip install -q --upgrade pip
& $VenvPython -m pip install -q -e ".[dev]"

$envExample = Join-Path $OrchRoot ".env.example"
$envFile = Join-Path $OrchRoot ".env"
if ((Test-Path $envExample) -and -not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "  Created apps\orchestrator\.env from .env.example"
}
Pop-Location

if (-not $SkipDashboard) {
    Write-Step "Installing dashboard dependencies"
    Push-Location $DashRoot
    & npm install --no-fund --no-audit
    Pop-Location
}

if (-not $SkipHooks) {
    Write-Step "Installing IDE hooks (Cursor + Claude Code)"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $RepoRoot "scripts\install_cursor_hooks.ps1")
    & powershell -ExecutionPolicy Bypass -File (Join-Path $RepoRoot "scripts\install_claude_hooks.ps1")
}

if (-not $NoDoctor) {
    Write-Step "Running agentmetry doctor"
    & $VenvPython -m cli doctor
}

Write-Host ""
Write-Host "Install complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Start:     scripts\start-dev.bat"
Write-Host "  2. Dashboard: http://localhost:3000"
Write-Host "  3. API:       http://localhost:8000"
Write-Host "  4. Selftest:  python scripts\agentmetry_ingest.py selftest"
Write-Host "  5. Trail:     scripts\agentmetry.bat verify --trail apps\orchestrator\data\audit-forward.jsonl"
Write-Host ""
if (-not $SkipHooks) {
    Write-Host "Fully quit and restart Cursor / Claude Code so hooks load." -ForegroundColor Yellow
}
