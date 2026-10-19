# Intune Proactive Remediation detection. Run in the user context.
# Exit 0 when doctor is clean, the recorder answers, and every present IDE
# surface is covered. Exit 1 on drift. absent is not drift (the agent is not
# installed). uncovered and unknown are.
$ErrorActionPreference = 'Continue'
$agentmetry = Get-Command agentmetry -ErrorAction SilentlyContinue
if (-not $agentmetry) {
    Write-Output 'agentmetry is not on PATH'
    exit 1
}

$raw = & agentmetry doctor --json
$doctorExit = $LASTEXITCODE
if (-not $raw) {
    Write-Output 'doctor --json produced no output'
    exit 1
}
try {
    $doc = $raw | ConvertFrom-Json
} catch {
    Write-Output 'doctor --json did not return JSON'
    exit 1
}
if ($doctorExit -ne 0 -or $doc.exit_code -ne 0) {
    Write-Output "doctor exit $doctorExit"
    exit 1
}
if (-not $doc.orchestrator_reachable) {
    Write-Output 'orchestrator not reachable'
    exit 1
}
foreach ($name in @($doc.hooks.PSObject.Properties.Name)) {
    $state = [string]$doc.hooks.$name
    if ($state -eq 'uncovered' -or $state -eq 'unknown') {
        Write-Output "$name is $state"
        exit 1
    }
}
Write-Output 'compliant'
exit 0
