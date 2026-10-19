#!/bin/sh
# LaunchAgent entry. Runs in the Aqua session as the developer.
# Installs IDE hooks only when `hooks status` exits 1. Rewriting on every
# interval would change mtimes and hide a later tamper watcher.
# Does not write the daemon data directory.
set -eu
LOG="${HOME}/Library/Logs/Agentmetry/coverage.log"
mkdir -p "$(dirname "$LOG")"
BIN=/usr/local/bin/agentmetry
status=0
"$BIN" hooks status --user-profile-dir "$HOME" >>"$LOG" 2>&1 || status=$?
if [ "$status" -eq 1 ]; then
    "$BIN" hooks install --user-profile-dir "$HOME" >>"$LOG" 2>&1
fi
exit 0
