# Install Agentmetry hooks for Google Antigravity 2.0 (global + scratch workspace).
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\install_antigravity_hooks.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Ingest = Join-Path $RepoRoot "scripts\agentmetry_ingest.py"
$Wrapper = Join-Path $RepoRoot "scripts\agentmetry_antigravity_hook.cmd"
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

@(
    "@echo off",
    "setlocal",
    "set AGENTMETRY_SOURCE_APP=antigravity",
    "set AGENTMETRY_HOOK_DEBUG=1",
    "`"$Python`" `"$Ingest`" antigravity hook %1"
) | Set-Content -Path $Wrapper -Encoding ascii

$HookCmd = "`"$Wrapper`""

# Tool names read from this machine's Antigravity conversation databases.
# Matching only run_command dropped every file read, write and search.
$ToolMatchers = @(
    "run_command", "view_file", "write_to_file", "replace_file_content",
    "multi_replace_file_content", "grep_search", "list_dir", "find_by_name",
    "search_web", "read_url_content", "generate_image", "schedule",
    "manage_task", "send_message", "ask_question", "ask_permission",
    "manage_subagents", "invoke_subagent", "list_permissions"
)

function New-ToolHook($hookName, $matcher) {
    @{
        matcher = $matcher
        hooks = @(
            @{
                type = "command"
                command = "$HookCmd $hookName"
                timeout = 15
            }
        )
    }
}

$agentmetry = @{
    PreToolUse = @($ToolMatchers | ForEach-Object { New-ToolHook "PreToolUse" $_ })
    PostToolUse = @($ToolMatchers | ForEach-Object { New-ToolHook "PostToolUse" $_ })
    Stop = @(
        @{
            type = "command"
            command = "$HookCmd Stop"
            timeout = 15
        }
    )
}

function Write-HooksFile($Path) {
    $dir = Split-Path $Path -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $json = ($agentmetry | ConvertTo-Json -Depth 10)
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  -> $Path"
}

Write-Host "Installing Agentmetry Antigravity hooks..."
Write-HooksFile (Join-Path $env:USERPROFILE ".gemini\config\hooks.json")
Write-HooksFile (Join-Path $env:USERPROFILE ".gemini\antigravity\scratch\.agents\hooks.json")
Write-HooksFile (Join-Path $RepoRoot ".agents\hooks.json")

Write-Host ""
Write-Host "IMPORTANT: Fully QUIT Antigravity (File -> Exit), then reopen."
Write-Host "Run ONE agent command (Get-Location), then check:"
Write-Host "  Get-Content $RepoRoot\apps\orchestrator\data\antigravity-hook-debug.log -Tail 3"
Write-Host "  Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/audit/tail?sources=antigravity&limit=5'"
