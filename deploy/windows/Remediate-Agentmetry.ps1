# Intune Proactive Remediation remediation. Prefer the user context so
# `hooks install` writes the developer profile. ACL hardening needs SYSTEM
# or an administrator; when this process is not elevated it warns and still
# installs hooks. A failed trail post does not fail the script: Intune would
# otherwise reinstall on a loop.
$ErrorActionPreference = 'Continue'
$agentmetry = Get-Command agentmetry -ErrorAction SilentlyContinue
if (-not $agentmetry) {
    Write-Output 'agentmetry is not on PATH'
    exit 1
}

& agentmetry hooks install
if ($LASTEXITCODE -ne 0) {
    Write-Output "hooks install failed ($LASTEXITCODE)"
    exit $LASTEXITCODE
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$protect = Join-Path $PSScriptRoot 'Protect-AgentmetryData.ps1'
if ($isAdmin -and (Test-Path $protect)) {
    & $protect
    if ($LASTEXITCODE -ne 0) {
        Write-Warning 'icacls hardening failed; hooks were still installed'
    }
} else {
    Write-Warning 'Not elevated. Trail ACLs were not changed. Run Protect-AgentmetryData.ps1 as SYSTEM.'
}

$hook = Get-Command agentmetry-hook -ErrorAction SilentlyContinue
if (-not $hook) {
    Write-Warning 'agentmetry-hook is not on PATH; hooks were installed but the trail was not told'
    exit 0
}
$payload = '{"event_type":"hook_remediation","source_app":"agentmetry","outcome":"success","reason":"intune remediate reinstalled hooks"}'
$payload | & agentmetry-hook send
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'hook_remediation was not accepted; install already succeeded'
}
exit 0
