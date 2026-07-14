#!/usr/bin/env python3
"""One command to see the dashboard with a realistic story in it.

    python scripts/demo_dashboard.py

Seeds a demo trail (5 sessions, 4 detections), then serves the built dashboard
+ API on http://127.0.0.1:8010. Open that URL. Ctrl-C to stop.

Uses a throwaway trail (data/demo-trail.jsonl) and a non-default port, so it
never touches your real audit data and your IDE hooks (which target :8000) can't
leak your live session into the demo.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_ORCH = _REPO / "apps" / "orchestrator"
_TRAIL = _ORCH / "data" / "demo-trail.jsonl"
_PORT = "8010"


def main() -> int:
    print("Seeding demo trail…")
    seed = subprocess.run([sys.executable, str(_REPO / "scripts" / "seed_demo.py")],
                          capture_output=True, text=True)
    for line in seed.stdout.splitlines():
        if line.strip().startswith(("seeded", "[", "detections", "sessions")):
            print("  " + line.strip())
    if seed.returncode != 0:
        print(seed.stderr[-1500:], file=sys.stderr)
        return 1

    if not (_REPO / "apps" / "dashboard" / "out" / "index.html").exists():
        print("\nNote: dashboard static export not found. Build it once with:")
        print("  cd apps/dashboard && npm install && npm run build")
        print("The API will still serve; the UI needs that build.\n")

    env = {
        **os.environ,
        "AGENTMETRY_AUDIT_EXPORT_PATH": str(_TRAIL),
        "AGENTMETRY_LLM_PROVIDER": "mock",
        "AGENTMETRY_ALLOW_MOCK": "1",
        "AGENTMETRY_STARTUP_VAULT_INDEX": "0",
        "AGENTMETRY_AUDIT_INGEST_ENABLED": "0",  # read-only demo; don't accept new events
    }
    print(f"\n  Dashboard  ->  http://127.0.0.1:{_PORT}/")
    print("  Try: click the red CRITICAL banner on a flagged session, then 'Analytics'.")
    print("  Ctrl-C to stop.\n")
    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--port", _PORT, "--log-level", "warning"],
            cwd=_ORCH, env=env,
        )
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
