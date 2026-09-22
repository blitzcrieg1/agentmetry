#!/usr/bin/env bash
# Agentmetry local launcher (Linux/macOS) — no Docker required.
# Mirrors scripts/start-dev.bat: orchestrator on :8000, dashboard on :3000.
#
# Both processes run in the background with logs under
# apps/orchestrator/data/logs/, and their PIDs are written to
# scripts/.dev.pids so `scripts/stop-dev.sh` can stop them.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORCH_ROOT="$REPO_ROOT/apps/orchestrator"
DASH_ROOT="$REPO_ROOT/apps/dashboard"
PID_FILE="$SCRIPT_DIR/.dev.pids"
LOG_DIR="$ORCH_ROOT/data/logs"
mkdir -p "$LOG_DIR"

VENV_PY="$ORCH_ROOT/.venv/bin/python"
[ -x "$VENV_PY" ] || {
  echo "No orchestrator virtualenv at $VENV_PY."
  echo "Run scripts/install.sh first (or create the venv manually)."
  exit 1
}

if [ -f "$PID_FILE" ]; then
  while read -r pid name; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "Already running: $name (pid $pid). Stop it first: scripts/stop-dev.sh"
      exit 1
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

command -v npm >/dev/null 2>&1 || {
  echo "npm not found on PATH. Install Node 18+ or run the orchestrator alone:"
  echo "  \"$VENV_PY\" -m uvicorn agentmetry.api.main:app --reload --port 8000"
  exit 1
}

echo "Starting orchestrator (log: $LOG_DIR/orchestrator-dev.log)..."
(
  cd "$ORCH_ROOT"
  if [ -f .env ]; then set -a; . ./.env; set +a; fi
  exec "$VENV_PY" -m uvicorn agentmetry.api.main:app --reload --port 8000
) > "$LOG_DIR/orchestrator-dev.log" 2>&1 &
ORCH_PID=$!

echo "Starting dashboard (log: $LOG_DIR/dashboard-dev.log)..."
(
  cd "$DASH_ROOT"
  exec npm run dev
) > "$LOG_DIR/dashboard-dev.log" 2>&1 &
DASH_PID=$!

printf '%s orchestrator\n%s dashboard\n' "$ORCH_PID" "$DASH_PID" > "$PID_FILE"

cleanup_on_fail() {
  kill "$ORCH_PID" "$DASH_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
}
trap cleanup_on_fail EXIT

sleep 2
kill -0 "$ORCH_PID" 2>/dev/null || { echo "Orchestrator exited immediately — see $LOG_DIR/orchestrator-dev.log"; exit 1; }
kill -0 "$DASH_PID" 2>/dev/null || { echo "Dashboard exited immediately — see $LOG_DIR/dashboard-dev.log"; exit 1; }
trap - EXIT

echo
echo "Agentmetry is running."
echo "  Dashboard:   http://localhost:3000"
echo "  API:         http://localhost:8000"
echo "  Orchestrator log: $LOG_DIR/orchestrator-dev.log"
echo "  Dashboard log:    $LOG_DIR/dashboard-dev.log"
echo "  Stop everything:  scripts/stop-dev.sh"
