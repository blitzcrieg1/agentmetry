# Restrict C:\ProgramData\Agentmetry so a user-space agent cannot modify or
# delete the trail or policy.yaml. Run as SYSTEM or Administrators.
# Users may read the policy and may modify the spool (hooks append there).
# SIDs, not display names: SYSTEM S-1-5-18, Administrators S-1-5-32-544,
# Users S-1-5-32-545.
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:ProgramData 'Agentmetry'
$trail = Join-Path $root 'trail'
$policy = Join-Path $root 'policy.yaml'
$spool = Join-Path $root 'spool'

New-Item -ItemType Directory -Force -Path $root, $trail, $spool | Out-Null
if (-not (Test-Path $policy)) {
    New-Item -ItemType File -Force -Path $policy | Out-Null
}

$system = '*S-1-5-18'
$admins = '*S-1-5-32-544'
$users = '*S-1-5-32-545'

function Invoke-Icacls {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ArgumentList)
    & icacls @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "icacls failed ($LASTEXITCODE): $($ArgumentList -join ' ')"
    }
}

Invoke-Icacls $trail /inheritance:r /grant:r "${system}:(OI)(CI)F" "${admins}:(OI)(CI)F"
Invoke-Icacls $policy /inheritance:r /grant:r "${system}:F" "${admins}:F" "${users}:R"
Invoke-Icacls $spool /inheritance:r /grant:r "${system}:(OI)(CI)F" "${admins}:(OI)(CI)F" "${users}:(OI)(CI)M"
Write-Output "hardened $trail and $policy"
exit 0
