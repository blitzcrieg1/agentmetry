#!/usr/bin/env bash
# Stop what scripts/start-dev.sh started: the orchestrator and the dashboard.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.dev.pids"

if [ ! -f "$PID_FILE" ]; then
  echo "Nothing to stop (no $PID_FILE). Is start-dev.sh running?"
  exit 0
fi

rc=0
while read -r pid name; do
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "Stopped $name (pid $pid)"
  else
    echo "$name (pid $pid) was not running"
  fi
done < "$PID_FILE"
rm -f "$PID_FILE"
exit "$rc"
