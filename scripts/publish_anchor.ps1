<#
.SYNOPSIS
  Take a checkpoint of the trail and publish it to the anchor repository.

.DESCRIPTION
  The hash chain is computed on this machine from a file on this machine, so
  anyone who can rewrite the trail can rewrite the proof that it was not
  rewritten. Publishing the Merkle root to a remote with force-push blocked is
  what closes that: any later edit below the published tree size produces a root
  that no longer matches a commit this machine cannot alter.

  Only the root leaves. It is a hash over hashes and discloses nothing about the
  events underneath it.

  Safe to run on a schedule. If no new records have arrived since the last
  checkpoint it exits without committing, so a quiet day does not fill the
  anchor log with duplicates.

.PARAMETER Trail
  JSONL trail to anchor. Defaults to the orchestrator's configured trail.

.PARAMETER AnchorRepo
  Working copy of the anchor repository.

.PARAMETER HostName
  Subdirectory in the anchor repo, so several machines can share one repository.

.EXAMPLE
  pwsh scripts/publish_anchor.ps1
#>
[CmdletBinding()]
param(
    [string]$Trail = "",
    [string]$AnchorRepo = "$env:USERPROFILE\Projects\agentmetry-anchors",
    [string]$HostName = "home-lab"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$orchestrator = Join-Path $repoRoot "apps\orchestrator"
$python = Join-Path $orchestrator ".venv\Scripts\python.exe"

if (-not $Trail) { $Trail = Join-Path $orchestrator "data\agentmetry-trail.jsonl" }
if (-not (Test-Path $Trail)) { Write-Error "No trail at $Trail"; exit 1 }
if (-not (Test-Path $python)) { Write-Error "No interpreter at $python"; exit 1 }
if (-not (Test-Path (Join-Path $AnchorRepo ".git"))) {
    Write-Error "$AnchorRepo is not a git working copy. Clone the anchor repo there first."
    exit 1
}

$anchorDir = Join-Path $AnchorRepo $HostName
$anchorFile = Join-Path $anchorDir ("{0}.anchors.jsonl" -f [IO.Path]::GetFileNameWithoutExtension($Trail))
New-Item -ItemType Directory -Force -Path $anchorDir | Out-Null

# Pull first. A push that fails on a stale ref after the checkpoint is already
# written leaves a local commitment with nothing backing it, which is the one
# state worth avoiding: it reads as anchored and is not.
Push-Location $AnchorRepo
try {
    git pull --ff-only --quiet origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Could not fast-forward the anchor repo. Resolve it by hand."
        exit 1
    }
} finally { Pop-Location }

# Has anything actually arrived since last time?
$before = 0
if (Test-Path $anchorFile) {
    $lastLine = Get-Content $anchorFile -Tail 1
    if ($lastLine) { $before = ([int](($lastLine | ConvertFrom-Json).tree_size)) }
}

$statement = & $python -m agentmetry.cli anchor $Trail --print 2>&1
if ($LASTEXITCODE -ne 0) { Write-Error "Could not build a checkpoint: $statement"; exit 1 }
$current = [int]([regex]::Match($statement, 'tree_size=(\d+)').Groups[1].Value)

if ($current -le $before) {
    Write-Host "No new records since tree size $before. Nothing to anchor."
    exit 0
}

& $python -m agentmetry.cli anchor $Trail --anchors $anchorFile
if ($LASTEXITCODE -ne 0) { Write-Error "Checkpoint failed."; exit 1 }

Push-Location $AnchorRepo
try {
    git add -- $anchorFile
    git commit --quiet -m "anchor: $HostName $([IO.Path]::GetFileName($Trail)) at tree_size $current"
    git push --quiet origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Push failed. The checkpoint is recorded locally but NOT anchored."
        exit 1
    }
    $sha = (git rev-parse --short HEAD)
    Write-Host "Anchored records $($before + 1)-$current in commit $sha"
} finally { Pop-Location }

# Verify against the copy that was just published rather than the one beside the
# trail. Checking the local sidecar would only confirm the file agrees with
# itself, which it always will.
& $python -m agentmetry.cli verify $Trail --trail --anchors $anchorFile
exit $LASTEXITCODE
