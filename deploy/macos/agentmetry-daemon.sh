#!/bin/sh
# LaunchDaemon entry. Runs the orchestrator as root over /var/db/agentmetry.
# A single-user Mac may place one absolute home path in
# /var/db/agentmetry/user-profile (root-owned, one line). The LaunchAgent
# must not write that file: if it can, the split is cosmetic.
set -eu
DATA=/var/db/agentmetry
PROFILE_FILE="$DATA/user-profile"
mkdir -p "$DATA/logs"
BIN=/usr/local/bin/agentmetry
set -- serve --host 127.0.0.1 --port 8000 --data-dir "$DATA" --policy-dir /etc/agentmetry
if [ -f "$PROFILE_FILE" ]; then
    profile=$(head -n 1 "$PROFILE_FILE")
    case "$profile" in
        /*) set -- "$@" --user-profile-dir "$profile" ;;
    esac
fi
exec "$BIN" "$@"
