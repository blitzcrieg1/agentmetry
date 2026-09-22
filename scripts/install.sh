#!/usr/bin/env bash
# Agentmetry: Linux/macOS one-flow install (orchestrator + dashboard + IDE hooks).
#
# Usage (from repo root):
#   bash scripts/install.sh
#
# Options:
#   --skip-hooks         Do not install IDE hooks (Claude Code, Cursor, Codex, ...)
#   --skip-dashboard     Skip npm install for apps/dashboard
#   --no-doctor          Skip agentmetry doctor at the end
#   --tool-policy-block  Set AGENTMETRY_TOOL_POLICY_MODE=block in orchestrator .env
#   --dlp-block          Set AGENTMETRY_DLP_MODE=block in orchestrator .env
#
# Doctor runs with --fix so fresh clones get vault/.system/drivers.json from the example.
#
# Hooks are installed through `agentmetry hooks install`, the cross-platform
# Python installer (cursor, claude, codex, qwen, kimi, qoder, codebuddy) rather
# than the Windows-only scripts/install_*_hooks.ps1 pair. Antigravity is not
# covered here: its hooks live in ~/.gemini and only the .ps1 writes them.

set -euo pipefail

SKIP_HOOKS=0
SKIP_DASHBOARD=0
NO_DOCTOR=0
TOOL_POLICY_BLOCK=0
DLP_BLOCK=0

for arg in "$@"; do
  case "$arg" in
    --skip-hooks) SKIP_HOOKS=1 ;;
    --skip-dashboard) SKIP_DASHBOARD=1 ;;
    --no-doctor) NO_DOCTOR=1 ;;
    --tool-policy-block) TOOL_POLICY_BLOCK=1 ;;
    --dlp-block) DLP_BLOCK=1 ;;
    -h|--help)
      sed -n '2,15p' "$0"; exit 0 ;;
    *)
      echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORCH_ROOT="$REPO_ROOT/apps/orchestrator"
DASH_ROOT="$REPO_ROOT/apps/dashboard"
VENV_DIR="$ORCH_ROOT/.venv"

if [ -t 1 ]; then
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_OFF=""
fi

step() { printf '\n%s==> %s%s\n' "$C_CYAN" "$1" "$C_OFF"; }
die()  { printf '%s%s%s\n' "$C_RED" "$1" "$C_OFF" >&2; exit 1; }

find_python() {
  # macOS ships "python3" only; some distros alias "python" to python3, and
  # some to nothing at all. Prefer whichever one actually talks 3.11+.
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
      if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        printf '%s' "$cand"; return 0
      fi
      PY_BAD="$cand"
    fi
  done
  return 1
}

printf '%s\n' "Agentmetry install"
printf 'Repo: %s\n' "$REPO_ROOT"

step "Checking prerequisites"
PY="$(find_python)" || {
  die "Python 3.11+ required, and $PY_BAD on PATH is older or missing.
Install from https://www.python.org/downloads/ (macOS: brew install python@3.12)
or your package manager, then re-run."
}
PYVER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
printf '  Python %s OK (%s)\n' "$PYVER" "$PY"

if [ "$SKIP_DASHBOARD" -eq 0 ]; then
  command -v node >/dev/null 2>&1 || die "node not found on PATH (dashboard needs Node 18+). Install from https://nodejs.org/ or re-run with --skip-dashboard."
  command -v npm  >/dev/null 2>&1 || die "npm not found on PATH. Install Node 18+ from https://nodejs.org/ or re-run with --skip-dashboard."
  printf '  Node %s OK\n' "$(node -v | sed 's/^v//')"
fi

step "Creating orchestrator virtualenv"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  "$PY" -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"
"$VENV_PY" -m pip install -q --upgrade pip
"$VENV_PY" -m pip install -q -e "$ORCH_ROOT[dev]"

ENV_EXAMPLE="$ORCH_ROOT/.env.example"
ENV_FILE="$ORCH_ROOT/.env"
if [ -f "$ENV_EXAMPLE" ] && [ ! -f "$ENV_FILE" ]; then
  cp "$ENV_EXAMPLE" "$ENV_FILE"
  printf '  Created apps/orchestrator/.env from .env.example\n'
fi

set_env_key() {
  # Same helper the Windows installer uses, so both platforms write .env
  # identically (idempotent upsert, no duplicate keys on re-run).
  [ -f "$ENV_FILE" ] || { [ -f "$ENV_EXAMPLE" ] && cp "$ENV_EXAMPLE" "$ENV_FILE" || : > "$ENV_FILE"; }
  "$VENV_PY" - "$ENV_FILE" "$1" "$2" <<'PYEOF'
import sys
from pathlib import Path
from agentmetry.core.diagnostics.env_file import upsert_env_key
upsert_env_key(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
PYEOF
  printf '  %s=%s\n' "$1" "$2"
}

if [ "$TOOL_POLICY_BLOCK" -eq 1 ]; then set_env_key AGENTMETRY_TOOL_POLICY_MODE block; fi
if [ "$DLP_BLOCK" -eq 1 ]; then set_env_key AGENTMETRY_DLP_MODE block; fi

if [ "$SKIP_DASHBOARD" -eq 0 ]; then
  step "Installing dashboard dependencies"
  # npm ci installs exactly what package-lock.json pins, matching install.ps1.
  (cd "$DASH_ROOT" && npm ci --no-fund --no-audit)
fi

if [ "$SKIP_HOOKS" -eq 0 ]; then
  step "Installing IDE hooks (every supported agent present on this machine)"
  # Failure here must fail the install: a recorder whose claim is that removal
  # changes what it says about itself cannot report success after a failure
  # (the issue #137 lesson, kept on this platform too).
  if ! "$VENV_PY" -m agentmetry.cli hooks install; then
    printf '\n%sHook install FAILED. Hooks are NOT installed, so nothing will be recorded.%s\n' "$C_RED" "$C_OFF"
    printf 'Re-run with --skip-hooks to install everything else, then fix hooks separately.\n'
    exit 1
  fi
fi

if [ "$NO_DOCTOR" -eq 0 ]; then
  step "Running agentmetry doctor"
  "$VENV_PY" -m agentmetry.cli doctor --fix
fi

printf '\n%sInstall complete.%s\n\n' "$C_GREEN" "$C_OFF"
printf 'Next steps:\n'
printf '  1. Start:     scripts/start-dev.sh\n'
printf '  2. Dashboard: http://localhost:3000\n'
printf '  3. API:       http://localhost:8000\n'
printf '  4. Selftest:  "%s" "%s" selftest\n' "$VENV_PY" "$REPO_ROOT/scripts/agentmetry_ingest.py"
printf '  5. Trail:     "%s" -m agentmetry.cli verify --trail apps/orchestrator/data/audit-forward.jsonl\n' "$VENV_PY"
printf '  6. Stats:     "%s" -m agentmetry.cli stats --days 7\n' "$VENV_PY"
printf '  7. Stop:      scripts/stop-dev.sh\n'
if [ "$TOOL_POLICY_BLOCK" -eq 1 ] || [ "$DLP_BLOCK" -eq 1 ]; then
  printf '\n%sHook enforcement enabled in apps/orchestrator/.env. Restart Claude Code / Cursor after hooks install.%s\n' "$C_YELLOW" "$C_OFF"
fi
if [ "$SKIP_HOOKS" -eq 0 ]; then
  printf '\n%sFully quit and restart Claude Code / Cursor (and any other hooked agent) so hooks load.%s\n' "$C_YELLOW" "$C_OFF"
fi
