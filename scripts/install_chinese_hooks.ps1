# Install Agentmetry hooks for all supported Chinese CLI agents.
# Skips agents whose config dirs are missing (not installed on this machine).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_chinese_hooks.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python -ErrorAction Stop).Source
$Bootstrap = Join-Path $RepoRoot "apps\orchestrator\core\audit\hook_bootstrap.py"

$targets = @(
    @{ Name = "Qwen Code"; Target = "qwen"; Config = "$env:USERPROFILE\.qwen" },
    @{ Name = "Kimi Code"; Target = "kimi"; Config = "$env:USERPROFILE\.kimi-code" },
    @{ Name = "Qoder"; Target = "qoder"; Config = "$env:USERPROFILE\.qoder" },
    @{ Name = "CodeBuddy"; Target = "codebuddy"; Config = "$env:USERPROFILE\.codebuddy" }
)

foreach ($t in $targets) {
    Write-Host ""
    Write-Host "=== $($t.Name) ===" -ForegroundColor Cyan
    if (-not (Test-Path $t.Config)) {
        Write-Host "SKIP: $($t.Config) not found - $($t.Name) may not be installed." -ForegroundColor Yellow
        continue
    }
    & $Python $Bootstrap $t.Target
    Write-Host "Installed hooks for $($t.Name). Quit and reopen the CLI once."
}

Write-Host ""
Write-Host "Preflight (per installed agent):" -ForegroundColor Green
Write-Host "  Set AGENTMETRY_SOURCE_APP then run: python scripts/agentmetry_ingest.py selftest"
