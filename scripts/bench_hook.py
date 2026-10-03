#!/usr/bin/env python3
"""Measure what one hook invocation costs the agent (pilot hardening item 23).

Runs the real hook process, the way an IDE does, against a stub ingest server
on an ephemeral port, so the number includes interpreter start, imports, DLP
and policy evaluation, the POST, and exit. It never talks to a running
orchestrator: the stub is the only endpoint, and the data directory is a
temporary one.

    python scripts/bench_hook.py            # 30 runs, prints p50/p95/max
    python scripts/bench_hook.py --runs 100 --budget-ms 100

Exits 1 when p50 exceeds --budget-ms, so CI can hold the line. The absolute
number depends on the machine; compare runs on the same one.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_PAYLOAD = {
    "session_id": "bench-session",
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "git status --short", "description": "check the tree"},
    "cwd": "/home/dev/project",
}


class _Ingest(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        body = b'{"accepted": 1}'
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def measure(runs: int, *, command: list[str] | None = None) -> list[float]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Ingest)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    cmd = command or [sys.executable, "-m", "agentmetry.hooks.ingest", "claude", "hook", "PreToolUse"]
    timings: list[float] = []
    with tempfile.TemporaryDirectory() as data:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTMETRY_")}
        env.update({
            "AGENTMETRY_URL": base,
            "AGENTMETRY_AUDIT_INGEST_URL": base,
            "AGENTMETRY_DATA_DIR": data,
            "AGENTMETRY_API_KEY": "bench-token",
        })
        stdin = json.dumps(_PAYLOAD)
        for _ in range(runs + 2):
            start = time.perf_counter()
            subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, cwd=data, check=False)
            timings.append((time.perf_counter() - start) * 1000)
    server.shutdown()
    return timings[2:]  # the first two warm the OS file cache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--budget-ms", type=float, default=0.0, help="fail if p50 exceeds this")
    args = parser.parse_args(argv)
    timings = sorted(measure(args.runs))
    p50 = statistics.median(timings)
    p95 = timings[max(0, int(len(timings) * 0.95) - 1)]
    print(f"hook, {args.runs} runs: p50 {p50:.0f} ms, p95 {p95:.0f} ms, max {timings[-1]:.0f} ms")
    if args.budget_ms and p50 > args.budget_ms:
        print(f"over budget: p50 {p50:.0f} ms > {args.budget_ms:.0f} ms")
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "orchestrator"))
    raise SystemExit(main())
